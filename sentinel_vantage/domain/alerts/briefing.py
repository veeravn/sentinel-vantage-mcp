"""BriefingService — a compact market/strategy/alerts briefing from stored results.

Scheduled briefings query stored scores rather than re-scanning the market through an
LLM (design section 16). The same service backs the ``get_market_brief`` MCP tool.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from sentinel_vantage.domain.alerts.ports import AlertEventRepository
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService


class MarketBrief(BaseModel):
    as_of: datetime
    strategy: str
    top_trending: list[dict] = Field(default_factory=list)
    top_candidates: list[dict] = Field(default_factory=list)
    recent_alerts: list[dict] = Field(default_factory=list)


class BriefingService:
    def __init__(
        self,
        trend: TrendService,
        *,
        research: ResearchService | None = None,
        alert_events: AlertEventRepository | None = None,
    ) -> None:
        self.trend = trend
        self.research = research
        self.alert_events = alert_events

    async def brief(self, *, as_of: datetime, strategy: str = "GARP", top: int = 5) -> MarketBrief:
        scan = await self.trend.scan(as_of=as_of, limit=top)
        top_trending = [
            {"symbol": r.symbol, "trend_score": r.score, "reasons": r.reasons} for r in scan.results
        ]

        top_candidates: list[dict] = []
        if self.research is not None:
            rank = await self.research.rank(strategy, as_of=as_of, limit=top)
            top_candidates = [
                {"symbol": r.symbol, "research_score": r.score, "confidence": r.confidence}
                for r in rank.results
            ]

        recent_alerts: list[dict] = []
        if self.alert_events is not None:
            events = await self.alert_events.list_events(since=as_of - timedelta(days=1), limit=10)
            recent_alerts = [
                {
                    "rule_id": e.rule_id,
                    "symbol": e.symbol,
                    "severity": e.severity,
                    "created_at": e.created_at.isoformat(),
                }
                for e in events
            ]

        return MarketBrief(
            as_of=as_of,
            strategy=strategy,
            top_trending=top_trending,
            top_candidates=top_candidates,
            recent_alerts=recent_alerts,
        )
