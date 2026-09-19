"""Resolve the metric values a rule references, for a set of symbols at an as_of.

Pulls trend metrics from the trend scan, per-strategy research scores from the research
ranking, and event counts from stored events — only computing what the rules actually
reference. Missing values are simply omitted (a rule never fires on absent data).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sentinel_vantage.domain.catalysts.ports import EventRepository
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService

_TREND_METRICS = {
    "trend_score",
    "trend_confidence",
    "volume_ratio",
    "return_1d_pct",
    "rank_percentile",
}
_ALL = 10**9


class MetricResolver:
    def __init__(
        self,
        trend: TrendService,
        *,
        research: ResearchService | None = None,
        events: EventRepository | None = None,
    ) -> None:
        self.trend = trend
        self.research = research
        self.events = events

    async def resolve(
        self, symbols: list[str], as_of: datetime, *, metrics: Iterable[str]
    ) -> dict[str, dict[str, float]]:
        wanted = set(metrics)
        out: dict[str, dict[str, float]] = {s: {} for s in symbols}
        if not symbols:
            return out

        if wanted & _TREND_METRICS:
            scan = await self.trend.scan(as_of=as_of, universe=symbols, limit=_ALL)
            for r in scan.results:
                m = out.setdefault(r.symbol, {})
                m["trend_score"] = r.score
                m["trend_confidence"] = r.confidence
                if r.rank_percentile is not None:
                    m["rank_percentile"] = r.rank_percentile
                for key in ("volume_ratio", "return_1d_pct"):
                    if key in r.metrics:
                        m[key] = r.metrics[key]

        strategies = {m.split(":", 1)[1] for m in wanted if m.startswith("research_score:")}
        if strategies and self.research is not None:
            for strat in strategies:
                rank = await self.research.rank(strat, as_of=as_of, universe=symbols, limit=_ALL)
                for r in rank.results:
                    out.setdefault(r.symbol, {})[f"research_score:{r.strategy}"] = r.score
                    out.setdefault(r.symbol, {})[f"research_score:{strat}"] = r.score

        if "filings_24h" in wanted and self.events is not None:
            for s in symbols:
                evs = await self.events.get_events(
                    s, start=as_of - timedelta(days=1), end=as_of + timedelta(days=1)
                )
                out.setdefault(s, {})["filings_24h"] = float(len(evs))

        return out
