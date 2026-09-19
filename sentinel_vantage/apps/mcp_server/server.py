"""MCP server construction and tool registration.

Thin application layer over the domain services (design section 21): each tool maps
~1:1 to a TrendService method and wraps the result in the provenance envelope so every
response carries as_of / provider / feed / model_version / confidence. The server never
recomputes scores — it is downstream of the engine.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from mcp.server.mcpserver import MCPServer

from sentinel_vantage import __version__
from sentinel_vantage.apps.mcp_server.dependencies import build_trend_service
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


def build_server(settings: Settings | None = None, trend: TrendService | None = None) -> MCPServer:
    settings = settings or get_settings()
    trend = trend or build_trend_service(settings)
    mcp = MCPServer(name="sentinel-vantage", version=__version__)

    def _envelope(data: Any, *, model_version: str) -> dict[str, Any]:
        return make_envelope(
            data=data,
            provider=settings.provider_name,
            feed=settings.feed_label,
            model_version=model_version,
            confidence=None,  # per-result confidence lives inside each result
        ).model_dump(mode="json")

    @mcp.tool()
    async def get_status() -> dict[str, Any]:
        """Health and readiness of the Sentinel Vantage system.

        Returns dependency status (Postgres, Redis), environment, active data feed,
        and schema-conventions version. A status payload, not a scored result.
        """
        health = await check_health(settings)
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

        Returns each name's score, confidence, rank percentile, raw metrics, reason
        codes, and risk flags — plus the symbols excluded by eligibility gates. Scores
        are deterministic and produced by the engine, not the model.
        """
        scan = await trend.scan(
            as_of=utcnow(),
            horizon=horizon,
            sector=sector,
            limit=limit,
            min_confidence=min_confidence,
        )
        return _envelope(
            {
                "horizon": scan.horizon,
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
        analysis = await trend.analyze(symbol.upper(), as_of=utcnow(), horizon=horizon)
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
        history = await trend.score_history(
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
