"""MCP server construction and tool registration: a thin layer over the domain services
that wraps every result in the provenance envelope."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from sentinel_vantage import __version__
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.core.config import Settings, get_settings
from sentinel_vantage.core.envelope import make_envelope
from sentinel_vantage.core.health import check_health
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.core.versioning import (
    NO_MODEL,
    SCHEMA_CONVENTIONS_VERSION,
    TREND_MODEL_VERSION,
)
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService


def build_server(
    settings: Settings | None = None,
    *,
    trend: TrendService | None = None,
    research: ResearchService | None = None,
    catalysts: CatalystService | None = None,
    resources: MCPResources | None = None,
) -> MCPServer:
    """Build the MCP server, owning Postgres/Redis resources unless services or
    already-connected resources are injected (tests)."""
    settings = settings or get_settings()

    owns_resources = False
    if trend is not None:
        service = trend
        rank_cache = None
    else:
        if resources is None:
            resources = MCPResources.build(settings)
            owns_resources = True
        service = resources.service
        rank_cache = resources.rank_cache
        research = research or resources.research
        catalysts = catalysts or resources.catalysts

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[None]:
        if owns_resources and resources is not None:
            await resources.connect()
        try:
            yield
        finally:
            if owns_resources and resources is not None:
                await resources.close()

    mcp = MCPServer(name="sentinel-vantage", version=__version__, lifespan=lifespan)

    def _envelope(data: Any, *, model_version: str) -> dict[str, Any]:
        return make_envelope(
            data=data,
            provider=settings.provider_name,
            feed=settings.feed_label,
            model_version=model_version,
            confidence=None,
        ).model_dump(mode="json")

    async def _as_of():
        return await service.bars.latest_bar_ts() or utcnow()

    @mcp.tool()
    async def get_status() -> dict[str, Any]:
        """Health and readiness of the system: dependency status, environment, active
        feed, and schema-conventions version."""
        db = resources.db if resources else None
        redis = resources.redis if resources else None
        health = await check_health(settings, db=db, redis=redis)
        return _envelope(
            {
                "health": health.model_dump(),
                "schema_conventions_version": SCHEMA_CONVENTIONS_VERSION,
            },
            model_version=NO_MODEL,
        )

    @mcp.tool()
    async def scan_trending_stocks(
        horizon: str = "1d",
        sector: str | None = None,
        limit: int = 20,
        min_confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Rank the eligible universe by Trend Score for a horizon, serving the worker's
        Redis rank cache when warm and recomputing from Postgres when cold. A sector
        filter forces a recompute (the cache is not sector-partitioned)."""
        if rank_cache is not None and sector is None:
            cached = await rank_cache.top(horizon, limit=max(limit * 4, 100))
            shown = [r for r in cached if r.confidence >= min_confidence][:limit]
            if shown:
                return _envelope(
                    {
                        "horizon": horizon,
                        "source": "cache",
                        "results": [r.model_dump(mode="json") for r in shown],
                        "ineligible": [],
                    },
                    model_version=TREND_MODEL_VERSION,
                )

        scan = await service.scan(
            as_of=await _as_of(),
            horizon=horizon,
            sector=sector,
            limit=limit,
            min_confidence=min_confidence,
        )
        return _envelope(
            {
                "horizon": scan.horizon,
                "source": "compute",
                "universe_size": scan.universe_size,
                "results": [r.model_dump(mode="json") for r in scan.results],
                "ineligible": [e.model_dump(mode="json") for e in scan.ineligible],
            },
            model_version=TREND_MODEL_VERSION,
        )

    @mcp.tool()
    async def analyze_stock(symbol: str, horizon: str = "1d") -> dict[str, Any]:
        """Full trend evidence for one symbol; an ineligible symbol returns its gate
        failures rather than a misleading score."""
        analysis = await service.analyze(symbol.upper(), as_of=await _as_of(), horizon=horizon)
        return _envelope(analysis.model_dump(mode="json"), model_version=TREND_MODEL_VERSION)

    @mcp.tool()
    async def get_score_history(
        symbol: str,
        horizon: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Evolution of a symbol's Trend Score over an ISO-8601 UTC range (default the
        trailing 30 days), read from persisted snapshots."""
        end_dt = _parse_iso(end) or utcnow()
        start_dt = _parse_iso(start) or (end_dt - timedelta(days=30))
        history = await service.score_history(
            symbol.upper(), horizon=horizon, start=start_dt, end=end_dt
        )
        return _envelope(
            {
                "symbol": symbol.upper(),
                "horizon": horizon,
                "history": [r.model_dump(mode="json") for r in history],
            },
            model_version=TREND_MODEL_VERSION,
        )

    if research is not None:
        _register_research_tools(mcp, research, _envelope, _as_of)

    if catalysts is not None:
        _register_catalyst_tools(mcp, catalysts, _envelope, _as_of)

    if resources is not None:
        _register_alert_tools(mcp, resources, _envelope, _as_of)

    return mcp


def _register_alert_tools(mcp, resources, envelope, as_of_fn):
    import uuid

    from sentinel_vantage.core.timeutils import utcnow
    from sentinel_vantage.domain.alerts.models import AlertRule, RuleDSL, Watchlist
    from sentinel_vantage.domain.alerts.parse import parse_conditions

    @mcp.tool()
    async def create_watchlist(name: str, symbols: list[str]) -> dict[str, Any]:
        """Create a named watchlist of symbols; returns it with a generated id."""
        wl = Watchlist(
            watchlist_id=uuid.uuid4().hex,
            name=name,
            symbols=[s.upper() for s in symbols],
            created_at=utcnow(),
        )
        await resources.watchlists.save_watchlist(wl)
        return envelope(wl.model_dump(mode="json"), model_version=NO_MODEL)

    @mcp.tool()
    async def create_alert_rule(
        all_conditions: list[str],
        any_conditions: list[str] | None = None,
        symbols: list[str] | None = None,
        watchlist_id: str | None = None,
        cooldown_hours: float = 4.0,
        severity: str = "info",
        name: str | None = None,
    ) -> dict[str, Any]:
        """Store a structured alert rule for asynchronous evaluation by the scheduler.

        Conditions are strings like "trend_score >= 85" or "research_score:GARP >= 75";
        all of ``all_conditions`` and at least one of ``any_conditions`` must hold. Scope
        by explicit ``symbols`` or a ``watchlist_id``.
        """
        rule = AlertRule(
            rule_id=uuid.uuid4().hex,
            name=name,
            symbols=[s.upper() for s in (symbols or [])],
            watchlist_id=watchlist_id,
            rule=RuleDSL(
                all=parse_conditions(all_conditions),
                any=parse_conditions(any_conditions or []),
                cooldown_hours=cooldown_hours,
            ),
            severity=severity,  # type: ignore[arg-type]
            created_at=utcnow(),
        )
        await resources.alert_rules.save_rule(rule)
        return envelope(rule.model_dump(mode="json"), model_version=NO_MODEL)

    @mcp.tool()
    async def list_alert_events(
        since: str | None = None,
        severity: str | None = None,
        symbols: list[str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Retrieve triggered alert events (default: the last 24 hours)."""
        since_dt = _parse_iso(since) or (utcnow() - timedelta(days=1))
        events = await resources.alert_events.list_events(
            since=since_dt,
            severity=severity,
            symbols=[s.upper() for s in symbols] if symbols else None,
            limit=limit,
        )
        return envelope(
            {"events": [e.model_dump(mode="json") for e in events]}, model_version=NO_MODEL
        )

    @mcp.tool()
    async def get_watchlist_changes(watchlist_id: str, since: str | None = None) -> dict[str, Any]:
        """Summarize material trend-score and event changes for a watchlist since a time."""
        as_of = await as_of_fn()
        since_dt = _parse_iso(since) or (as_of - timedelta(days=1))
        changes = await resources.watchlist_service.changes(
            watchlist_id, since=since_dt, as_of=as_of
        )
        return envelope(changes.model_dump(mode="json"), model_version=NO_MODEL)

    @mcp.tool()
    async def get_market_brief(strategy: str = "GARP", top: int = 5) -> dict[str, Any]:
        """Compact briefing: top trending names, top research candidates, recent alerts."""
        brief = await resources.briefing.brief(as_of=await as_of_fn(), strategy=strategy, top=top)
        return envelope(brief.model_dump(mode="json"), model_version=NO_MODEL)


def _register_catalyst_tools(mcp, catalysts, envelope, as_of_fn):
    from sentinel_vantage.core.versioning import CATALYST_MODEL_VERSION

    @mcp.tool()
    async def explain_move(symbol: str, lookback_days: int = 20) -> dict[str, Any]:
        """Explain a symbol's largest recent 1-day move with ranked catalyst evidence from
        nearby SEC filings (weak/moderate/strong) and a causal-confidence label —
        correlation, never a proven cause."""
        result = await catalysts.explain_move(
            symbol.upper(), as_of=await as_of_fn(), lookback_days=lookback_days
        )
        return envelope(result.model_dump(mode="json"), model_version=CATALYST_MODEL_VERSION)


def _register_research_tools(mcp, research, envelope, as_of_fn):
    from sentinel_vantage.core.versioning import RESEARCH_MODEL_VERSION

    @mcp.tool()
    async def find_research_candidates(
        strategy: str = "GARP",
        sector: str | None = None,
        limit: int = 20,
        min_confidence: float = 0.0,
    ) -> dict[str, Any]:
        """Rank research candidates for a strategy (e.g. GARP): hard gates, then
        cross-sectional factor scoring with penalties over point-in-time SEC fundamentals.
        Returns each candidate's score, factor breakdown, and the names excluded by gates."""
        rank = await research.rank(
            strategy,
            as_of=await as_of_fn(),
            sector=sector,
            limit=limit,
            min_confidence=min_confidence,
        )
        return envelope(
            {
                "strategy": rank.strategy,
                "universe_size": rank.universe_size,
                "results": [r.model_dump(mode="json") for r in rank.results],
                "ineligible": [e.model_dump(mode="json") for e in rank.ineligible],
            },
            model_version=RESEARCH_MODEL_VERSION,
        )

    @mcp.tool()
    async def compare_stocks(symbols: list[str], strategy: str = "GARP") -> dict[str, Any]:
        """Side-by-side research scoring of specific symbols under a strategy, with factor
        breakdowns, penalties, and reason codes."""
        cmp = await research.compare(
            [s.upper() for s in symbols], strategy=strategy, as_of=await as_of_fn()
        )
        return envelope(
            {
                "strategy": cmp.strategy,
                "results": [r.model_dump(mode="json") for r in cmp.results],
                "ineligible": [e.model_dump(mode="json") for e in cmp.ineligible],
            },
            model_version=RESEARCH_MODEL_VERSION,
        )


def _parse_iso(value: str | None):
    if not value:
        return None
    from datetime import datetime

    from sentinel_vantage.core.timeutils import to_utc

    return to_utc(datetime.fromisoformat(value))
