"""MCP server construction and tool registration.

Thin application layer over the domain services (design section 21): each tool maps
~1:1 to a TrendService method and wraps the result in the provenance envelope so every
response carries as_of / provider / feed / model_version / confidence. The server never
recomputes scores as a source of truth — it reads the same Postgres/Redis state the
worker writes.

Wiring: without an injected service, ``MCPResources`` builds a Postgres-backed service
plus the Redis rank cache, and the server's lifespan connects/closes them. Tests inject
an in-memory service (``trend=``) and skip the lifespan entirely.

scan_trending_stocks prefers the worker's Redis rank cache (the fast path) and falls
back to an on-demand Postgres recompute when the cache is cold.
"""

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
from sentinel_vantage.domain.trend.service import TrendService


def build_server(
    settings: Settings | None = None,
    *,
    trend: TrendService | None = None,
    resources: MCPResources | None = None,
) -> MCPServer:
    """Build the MCP server.

    - default: build and own Postgres/Redis resources (lifespan connects + closes them).
    - ``resources=``: use caller-owned, already-connected resources (lifespan is a no-op;
      the caller manages their lifecycle — used by integration tests).
    - ``trend=``: inject an in-memory service; no external resources (unit tests).
    """
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
            confidence=None,  # per-result confidence lives inside each result
        ).model_dump(mode="json")

    async def _as_of():
        return await service.bars.latest_bar_ts() or utcnow()

    @mcp.tool()
    async def get_status() -> dict[str, Any]:
        """Health and readiness of the Sentinel Vantage system.

        Returns dependency status (Postgres, Redis), environment, active data feed,
        and schema-conventions version. A status payload, not a scored result.
        """
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
        """Rank the eligible universe by Trend Score for a horizon.

        Reads the worker's Redis rank cache when warm (``source: cache``); otherwise
        recomputes from Postgres on demand (``source: compute``). Each name carries its
        score, confidence, rank percentile, raw metrics, reason codes, and risk flags.
        Sector filtering forces a recompute (the cache is not sector-partitioned).
        """
        # Fast path: the worker's precomputed ranks.
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

        # Cold cache (or sector filter): recompute from Postgres.
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
        """Full trend evidence for one symbol, scored within the current universe.

        If the symbol fails eligibility gates it is returned as ineligible with the
        specific gate failures rather than a misleading score.
        """
        analysis = await service.analyze(symbol.upper(), as_of=await _as_of(), horizon=horizon)
        return _envelope(analysis.model_dump(mode="json"), model_version=TREND_MODEL_VERSION)

    @mcp.tool()
    async def get_score_history(
        symbol: str,
        horizon: str = "1d",
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        """Evolution of a symbol's Trend Score over a time range (ISO-8601 UTC).

        Defaults to the trailing 30 days. Reads persisted score snapshots; returns an
        empty series until the worker has recorded snapshots for the symbol.
        """
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

    return mcp


def _parse_iso(value: str | None):
    if not value:
        return None
    from datetime import datetime

    from sentinel_vantage.core.timeutils import to_utc

    return to_utc(datetime.fromisoformat(value))
