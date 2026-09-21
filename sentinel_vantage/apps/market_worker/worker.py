"""Market worker lifecycle — the always-on path that, on a cadence, scores the latest
stored session and publishes ranks, independent of any MCP client."""

from __future__ import annotations

import asyncio
import signal

from sentinel_vantage.apps.market_worker.scoring import run_scoring_cycle
from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.health import check_health
from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import (
    PostgresBarRepository,
    PostgresFeatureRepository,
    PostgresScoreRepository,
)
from sentinel_vantage.storage.rank_cache import RedisRankCache
from sentinel_vantage.storage.redis_store import RedisStore

log = get_logger("market_worker")


class MarketWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.postgres_dsn)
        self.redis = RedisStore(settings.redis_url)
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        await self.db.connect()
        await self.redis.connect()
        health = await check_health(self.settings, db=self.db, redis=self.redis)
        log.info("market_worker.started", feed=self.settings.feed_label, health=health.status.value)

        bars = PostgresBarRepository(self.db, benchmark_symbol="SPY")
        service = TrendService(
            bars,
            scores=PostgresScoreRepository(
                self.db, provider=self.settings.provider_name, feed=self.settings.feed_label
            ),
            features=PostgresFeatureRepository(
                self.db, provider=self.settings.provider_name, feed=self.settings.feed_label
            ),
        )
        rank_cache = RedisRankCache(self.redis)

        try:
            while not self._stop.is_set():
                try:
                    as_of = await bars.latest_bar_ts(timeframe="1d")
                    if as_of is None:
                        log.warning("market_worker.no_bars", hint="run sv-backfill first")
                    else:
                        await run_scoring_cycle(
                            service, rank_cache, horizon=self.settings.trend_horizon, as_of=as_of
                        )
                except Exception as exc:  # noqa: BLE001 - a bad cycle must not kill the worker
                    log.error("market_worker.cycle_failed", error=str(exc))

                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.scoring_interval_seconds
                    )
                except TimeoutError:
                    continue
        finally:
            await self.redis.close()
            await self.db.close()
            log.info("market_worker.stopped")


async def _run(settings: Settings) -> None:
    worker = MarketWorker(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.request_stop)
    await worker.run()
