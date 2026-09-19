"""Wiring for the MCP server's domain dependencies.

The server reads the same Postgres/Redis state the worker writes. ``MCPResources`` owns
the Database + RedisStore lifecycle (connected by the server's lifespan) and builds a
Postgres-backed TrendService plus the Redis rank cache. Tests inject an in-memory
service instead, so they need neither.
"""

from __future__ import annotations

from dataclasses import dataclass

from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import (
    PostgresBarRepository,
    PostgresEventRepository,
    PostgresFeatureRepository,
    PostgresFundamentalRepository,
    PostgresResearchScoreRepository,
    PostgresScoreRepository,
)
from sentinel_vantage.storage.rank_cache import RedisRankCache
from sentinel_vantage.storage.redis_store import RedisStore

BENCHMARK_SYMBOL = "SPY"


@dataclass
class MCPResources:
    settings: Settings
    db: Database
    redis: RedisStore
    service: TrendService
    research: ResearchService
    catalysts: CatalystService
    rank_cache: RedisRankCache

    @classmethod
    def build(cls, settings: Settings) -> MCPResources:
        db = Database(settings.postgres_dsn)
        redis = RedisStore(settings.redis_url)
        bars = PostgresBarRepository(db, benchmark_symbol=BENCHMARK_SYMBOL)
        provider, feed = settings.provider_name, settings.feed_label
        service = TrendService(
            bars,
            scores=PostgresScoreRepository(db, provider=provider, feed=feed),
            features=PostgresFeatureRepository(db, provider=provider, feed=feed),
        )
        research = ResearchService(
            bars,
            PostgresFundamentalRepository(db),
            scores=PostgresResearchScoreRepository(db, provider=provider, feed=feed),
        )
        catalysts = CatalystService(bars, PostgresEventRepository(db))
        return cls(settings, db, redis, service, research, catalysts, RedisRankCache(redis))

    async def connect(self) -> None:
        await self.db.connect()
        await self.redis.connect()

    async def close(self) -> None:
        await self.redis.close()
        await self.db.close()
