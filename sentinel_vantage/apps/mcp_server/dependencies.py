"""Wiring for the MCP server's domain dependencies.

Phase 1 defaults to in-memory repositories so the server runs and its tools are
exercisable without a live database. When the Postgres/Redis and Polygon
implementations land, only this factory changes — the tools and domain code do not.
"""

from __future__ import annotations

from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.memory import InMemoryBarRepository, InMemoryScoreRepository


def build_trend_service(settings: Settings) -> TrendService:
    # TODO(phase-1): swap for PostgresBarRepository + RedisScoreCache once migrations
    # and the Polygon ingestion path are in place.
    return TrendService(InMemoryBarRepository(), scores=InMemoryScoreRepository())
