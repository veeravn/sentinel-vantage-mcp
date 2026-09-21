"""Polygon.io market-data adapter over REST aggregates/quotes and the minute-aggregate
WebSocket. Parsing is factored into pure functions for testability; REST GETs are paced
by a rolling-window rate limiter and back off on 429/5xx."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import websockets

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.ratelimit import RateLimiter
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.providers.base import Bar, BarEvent, MarketDataProvider, Quote, Session

log = get_logger("polygon")

REST_BASE = "https://api.polygon.io"
WS_REALTIME = "wss://socket.polygon.io/stocks"
WS_DELAYED = "wss://delayed.polygon.io/stocks"

_TIMEFRAME = {
    "1m": (1, "minute"),
    "5m": (5, "minute"),
    "1h": (1, "hour"),
    "1d": (1, "day"),
}


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def bar_from_agg(symbol: str, agg: dict[str, Any], *, timeframe: str, feed: str) -> Bar:
    """Pure: map one Polygon aggregate object to a normalized Bar."""
    return Bar(
        symbol=symbol,
        ts=_ms_to_dt(agg["t"]),
        timeframe=timeframe,
        open=float(agg["o"]),
        high=float(agg["h"]),
        low=float(agg["l"]),
        close=float(agg["c"]),
        volume=float(agg["v"]),
        provider="polygon",
        feed=feed,
    )


def parse_ws_message(raw: str, *, feed: str) -> list[BarEvent]:
    """Pure: parse a Polygon WebSocket text frame into minute-aggregate (``ev == "AM"``)
    BarEvents; status/auth and non-AM events are ignored."""
    try:
        events = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(events, list):
        return []

    out: list[BarEvent] = []
    now = utcnow()
    for ev in events:
        if not isinstance(ev, dict) or ev.get("ev") != "AM":
            continue
        out.append(
            BarEvent(
                bar=Bar(
                    symbol=ev["sym"],
                    ts=_ms_to_dt(ev["s"]),
                    timeframe="1m",
                    open=float(ev["o"]),
                    high=float(ev["h"]),
                    low=float(ev["l"]),
                    close=float(ev["c"]),
                    volume=float(ev["v"]),
                    provider="polygon",
                    feed=feed,
                ),
                received_at=now,
            )
        )
    return out


class PolygonMarketDataProvider(MarketDataProvider):
    name = "polygon"

    def __init__(
        self,
        api_key: str,
        *,
        feed_mode: str = "delayed",
        requests_per_minute: int = 0,
        client: httpx.AsyncClient | None = None,
        base_url: str = REST_BASE,
    ) -> None:
        self._api_key = api_key
        self._feed_mode = feed_mode
        self.feed = f"polygon/{feed_mode}"
        self._ws_url = WS_REALTIME if feed_mode == "realtime" else WS_DELAYED
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self._limiter = RateLimiter(requests_per_minute)  # 0 = unlimited (paid tiers)

    async def close(self) -> None:
        await self._client.aclose()

    def _params(self, **extra: Any) -> dict[str, Any]:
        return {"apiKey": self._api_key, **extra}

    async def _get(
        self, path: str, params: dict[str, Any], *, max_retries: int = 6
    ) -> httpx.Response:
        """GET with proactive pacing and backoff on 429/5xx (honors ``Retry-After``,
        else exponential 1,2,4,… capped at 60s)."""
        delay = 1.0
        for attempt in range(max_retries + 1):
            await self._limiter.acquire()
            resp = await self._client.get(path, params=params)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                resp.raise_for_status()
                return resp
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            log.warning("polygon.retry", status=resp.status_code, wait=wait, path=path)
            await asyncio.sleep(min(wait, 60.0))
            delay = min(delay * 2, 60.0)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def get_bars(
        self, symbols: Sequence[str], timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        if timeframe not in _TIMEFRAME:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        mult, span = _TIMEFRAME[timeframe]
        frm, to = start.date().isoformat(), end.date().isoformat()

        bars: list[Bar] = []
        for sym in symbols:
            path = f"/v2/aggs/ticker/{sym}/range/{mult}/{span}/{frm}/{to}"
            resp = await self._get(path, self._params(adjusted="true", sort="asc", limit=50000))
            payload = resp.json()
            for agg in payload.get("results") or []:
                bars.append(bar_from_agg(sym, agg, timeframe=timeframe, feed=self.feed))
        return bars

    async def get_latest_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        quotes: list[Quote] = []
        for sym in symbols:
            resp = await self._get(
                f"/v3/quotes/{sym}",
                self._params(limit=1, order="desc", sort="timestamp"),
            )
            results = resp.json().get("results") or []
            if not results:
                continue
            q = results[0]
            ts_ns = q.get("sip_timestamp") or q.get("participant_timestamp")
            quotes.append(
                Quote(
                    symbol=sym,
                    ts=_ms_to_dt(ts_ns / 1_000_000) if ts_ns else utcnow(),
                    bid=q.get("bid_price"),
                    ask=q.get("ask_price"),
                    provider="polygon",
                    feed=self.feed,
                )
            )
        return quotes

    async def get_market_calendar(self, start: datetime, end: datetime) -> list[Session]:
        """Weekday trading sessions between start and end (UTC). Approximation: Mon-Fri
        09:30-16:00 ET as 13:30-20:00 UTC; holiday/DST-exact times are a later refinement."""
        sessions: list[Session] = []
        day = start.date()
        while day <= end.date():
            if day.weekday() < 5:
                base = datetime(day.year, day.month, day.day, tzinfo=UTC)
                sessions.append(
                    Session(
                        date=day.isoformat(),
                        open=base + timedelta(hours=13, minutes=30),
                        close=base + timedelta(hours=20),
                        is_open=True,
                    )
                )
            day += timedelta(days=1)
        return sessions

    async def stream_bars(self, symbols: Sequence[str] | str) -> AsyncIterator[BarEvent]:
        """Live minute-aggregate stream: authenticate, subscribe to ``AM.*`` (or the given
        symbols), and yield parsed BarEvents. Reconnect/gap-backfill is the worker's job."""
        if symbols == "*" or symbols == ["*"]:
            sub = "AM.*"
        else:
            sub = ",".join(f"AM.{s}" for s in symbols)

        async with websockets.connect(self._ws_url) as ws:
            await ws.send(json.dumps({"action": "auth", "params": self._api_key}))
            await ws.send(json.dumps({"action": "subscribe", "params": sub}))
            log.info("polygon.ws_subscribed", feed=self.feed, subscription=sub)
            async for raw in ws:
                for event in parse_ws_message(
                    raw if isinstance(raw, str) else raw.decode(), feed=self.feed
                ):
                    yield event
