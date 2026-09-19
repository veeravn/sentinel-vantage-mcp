"""Market worker lifecycle.

Phase 0: connect to storage, log a heartbeat, and shut down cleanly on signal. The
structure (async run loop, graceful shutdown, storage wiring) is what Phase 1 hangs
the ingestion and scoring pipeline on.
"""

from __future__ import annotations

import asyncio
import signal

from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.health import check_health
from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.redis_store import RedisStore

log = get_logger("market_worker")

HEARTBEAT_SECONDS = 30


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
        try:
            while not self._stop.is_set():
                # Phase 1: pull bars -> update features -> recompute trend scores here.
                log.info("market_worker.heartbeat")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_SECONDS)
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
