"""Wiring for the MCP server's dependencies: ``MCPResources`` owns the Database + RedisStore
lifecycle and builds the Postgres-backed services plus the Redis rank cache the server
reads (tests inject in-memory services instead)."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.briefing import BriefingService
from sentinel_vantage.domain.alerts.watchlist import WatchlistService
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.alert_repos import (
    PostgresAlertEventRepository,
    PostgresAlertRuleRepository,
    PostgresWatchlistRepository,
)
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
    watchlists: PostgresWatchlistRepository
    alert_rules: PostgresAlertRuleRepository
    alert_events: PostgresAlertEventRepository
    watchlist_service: WatchlistService
    briefing: BriefingService
    rank_cache: RedisRankCache

    @classmethod
    def build(cls, settings: Settings) -> MCPResources:
        db = Database(settings.postgres_dsn)
        redis = RedisStore(settings.redis_url)
        bars = PostgresBarRepository(db, benchmark_symbol=BENCHMARK_SYMBOL)
        provider, feed = settings.provider_name, settings.feed_label
        trend_scores = PostgresScoreRepository(db, provider=provider, feed=feed)
        events = PostgresEventRepository(db)
        service = TrendService(
            bars,
            scores=trend_scores,
            features=PostgresFeatureRepository(db, provider=provider, feed=feed),
        )
        research = ResearchService(
            bars,
            PostgresFundamentalRepository(db),
            scores=PostgresResearchScoreRepository(db, provider=provider, feed=feed),
        )
        catalysts = CatalystService(bars, events)

        watchlists = PostgresWatchlistRepository(db)
        alert_rules = PostgresAlertRuleRepository(db)
        alert_events = PostgresAlertEventRepository(db)
        watchlist_service = WatchlistService(watchlists, service, trend_scores, events)
        briefing = BriefingService(service, research=research, alert_events=alert_events)

        return cls(
            settings,
            db,
            redis,
            service,
            research,
            catalysts,
            watchlists,
            alert_rules,
            alert_events,
            watchlist_service,
            briefing,
            RedisRankCache(redis),
        )

    async def connect(self) -> None:
        await self.db.connect()
        await self.redis.connect()

    async def close(self) -> None:
        await self.redis.close()
        await self.db.close()
