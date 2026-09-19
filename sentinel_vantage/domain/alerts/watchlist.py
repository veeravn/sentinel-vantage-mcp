"""WatchlistService — summarize material changes for a watchlist since a timestamp.

Compares each symbol's current Trend Score against its last stored score before
``since`` and counts new events in between (design use case: "what changed in my
watchlist since yesterday?").
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sentinel_vantage.domain.alerts.models import SymbolChange, WatchlistChanges
from sentinel_vantage.domain.alerts.ports import WatchlistRepository
from sentinel_vantage.domain.catalysts.ports import EventRepository
from sentinel_vantage.domain.trend.ports import ScoreRepository
from sentinel_vantage.domain.trend.service import TrendService

_MATERIAL_DELTA = 5.0
_ALL = 10**9


class WatchlistService:
    def __init__(
        self,
        watchlists: WatchlistRepository,
        trend: TrendService,
        scores: ScoreRepository,
        events: EventRepository,
    ) -> None:
        self.watchlists = watchlists
        self.trend = trend
        self.scores = scores
        self.events = events

    async def changes(
        self, watchlist_id: str, *, since: datetime, as_of: datetime
    ) -> WatchlistChanges:
        wl = await self.watchlists.get_watchlist(watchlist_id)
        if wl is None or not wl.symbols:
            return WatchlistChanges(watchlist_id=watchlist_id, since=since, as_of=as_of)

        scan = await self.trend.scan(as_of=as_of, universe=list(wl.symbols), limit=_ALL)
        now = {r.symbol: r.score for r in scan.results}

        changes: list[SymbolChange] = []
        for sym in wl.symbols:
            prev_hist = await self.scores.get_trend_history(
                sym, horizon="1d", start=since - timedelta(days=30), end=since
            )
            prev = prev_hist[-1].score if prev_hist else None
            cur = now.get(sym)
            delta = (cur - prev) if (cur is not None and prev is not None) else None
            new_events = await self.events.get_events(sym, start=since, end=as_of)

            notes: list[str] = []
            if delta is not None and abs(delta) >= _MATERIAL_DELTA:
                notes.append(f"trend score moved {delta:+.1f}")
            if new_events:
                notes.append(f"{len(new_events)} new filing(s)")

            changes.append(
                SymbolChange(
                    symbol=sym,
                    trend_score_now=cur,
                    trend_score_prev=prev,
                    trend_score_delta=round(delta, 4) if delta is not None else None,
                    new_events=len(new_events),
                    notes=notes,
                )
            )
        return WatchlistChanges(
            watchlist_id=watchlist_id, since=since, as_of=as_of, changes=changes
        )
