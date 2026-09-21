"""Run the scheduler process: evaluate alert rules on a cadence (independent of any MCP
client) and run scheduled briefings."""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.domain.alerts.engine import AlertEngine
from sentinel_vantage.domain.alerts.resolver import MetricResolver
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
    PostgresFundamentalRepository,
)


async def _run() -> None:
    settings = get_settings()
    log = get_logger("scheduler")
    db = Database(settings.postgres_dsn)
    await db.connect()

    bars = PostgresBarRepository(db)
    resolver = MetricResolver(
        TrendService(bars),
        research=ResearchService(bars, PostgresFundamentalRepository(db)),
        events=PostgresEventRepository(db),
    )
    engine = AlertEngine(
        PostgresAlertRuleRepository(db),
        PostgresAlertEventRepository(db),
        resolver,
        watchlists=PostgresWatchlistRepository(db),
    )

    async def evaluate_alerts() -> None:
        try:
            fired = await engine.run_once()
            if fired:
                log.info("scheduler.alerts_fired", count=len(fired))
        except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the scheduler
            log.error("scheduler.alert_cycle_failed", error=str(exc))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(evaluate_alerts, "interval", seconds=settings.alert_interval_seconds)
    scheduler.start()
    log.info("scheduler.started", alert_interval_s=settings.alert_interval_seconds)

    stop = asyncio.Event()
    try:
        await stop.wait()  # run until the container/process is signalled to stop
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        log.info("scheduler.stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
