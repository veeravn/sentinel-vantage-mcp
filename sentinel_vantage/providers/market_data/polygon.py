"""Polygon.io market-data adapter.

Implements the MarketDataProvider port against Polygon's REST aggregates and quotes and
its minute-aggregate WebSocket. Every emitted Bar/Quote carries feed provenance
(``polygon/delayed`` or ``polygon/realtime``); Polygon delivers 100% consolidated
market coverage on every tier, so the volume-based trend features are honest even on the
free plan.

Parsing is factored into pure functions so the WebSocket path is unit-testable without a
live socket and the REST path with an httpx MockTransport.

Not in this adapter (deliberately, for later increments): Flat Files bulk backfill for
large historical loads, and rate-limit backoff for the free tier's 5 req/min cap.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import websockets

from sentinel_vantage.core.logging import get_logger
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
    """Pure: parse a Polygon WebSocket text frame into minute-aggregate BarEvents.

    Polygon frames are JSON arrays of events; minute aggregates have ``ev == "AM"``.
    Status/auth frames and non-AM events are ignored.
    """
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
        client: httpx.AsyncClient | None = None,
        base_url: str = REST_BASE,
    ) -> None:
        self._api_key = api_key
        self._feed_mode = feed_mode
        self.feed = f"polygon/{feed_mode}"
        self._ws_url = WS_REALTIME if feed_mode == "realtime" else WS_DELAYED
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _params(self, **extra: Any) -> dict[str, Any]:
        return {"apiKey": self._api_key, **extra}

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
            resp = await self._client.get(
                path, params=self._params(adjusted="true", sort="asc", limit=50000)
            )
            resp.raise_for_status()
            payload = resp.json()
            for agg in payload.get("results") or []:
                bars.append(bar_from_agg(sym, agg, timeframe=timeframe, feed=self.feed))
        return bars

    async def get_latest_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        quotes: list[Quote] = []
        for sym in symbols:
            resp = await self._client.get(
                f"/v3/quotes/{sym}",
                params=self._params(limit=1, order="desc", sort="timestamp"),
            )
            resp.raise_for_status()
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
        """Weekday trading sessions between start and end (UTC).

        Approximation: Mon-Fri, 09:30-16:00 ET rendered as 13:30-20:00 UTC. Holiday
        awareness and DST-exact session times are a later refinement; store timestamps
        stay UTC and calendar semantics stay separate from bar timestamps.
        """
        sessions: list[Session] = []
        day = start.date()
        while day <= end.date():
            if day.weekday() < 5:  # Mon-Fri
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
        """Live minute-aggregate stream over Polygon's WebSocket.

        Authenticates, subscribes to ``AM.*`` (or the given symbols), and yields parsed
        BarEvents. Reconnect/backfill of gaps is handled by the ingestion worker, not
        here — this coroutine surfaces a clean event stream.
        """
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
