"""Run the scheduler process: evaluate alert rules on a cadence (independent of any MCP
client) and run scheduled briefings."""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sentinel_vantage.apps.market_worker.backfill import backfill
from sentinel_vantage.apps.scheduler.notify import build_notifier, format_alert_message
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.domain.alerts.engine import AlertEngine
from sentinel_vantage.domain.alerts.resolver import MetricResolver
from sentinel_vantage.domain.market.universe import active_symbols, benchmark_symbol, seed_universe
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.providers.market_data.polygon import PolygonMarketDataProvider
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

    notifier = build_notifier(settings)

    async def evaluate_alerts() -> None:
        try:
            fired = await engine.run_once()
        except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the scheduler
            log.error("scheduler.alert_cycle_failed", error=str(exc))
            return
        if not fired:
            return
        log.info("scheduler.alerts_fired", count=len(fired))
        if notifier is not None:
            subject, body = format_alert_message(fired)
            try:
                await notifier.send(subject, body)
            except Exception as exc:  # noqa: BLE001 - delivery failure must not lose the alert
                log.error("scheduler.notify_failed", error=str(exc))

    async def daily_backfill() -> None:
        if not settings.polygon_api_key:
            log.warning("scheduler.backfill_skipped", reason="no polygon key")
            return
        provider = PolygonMarketDataProvider(
            settings.polygon_api_key,
            feed_mode=settings.feed_mode,
            requests_per_minute=settings.polygon_requests_per_minute,
        )
        try:
            await seed_universe(db)
            symbols = [benchmark_symbol(), *active_symbols()]
            total = await backfill(db, provider, symbols, days=settings.daily_backfill_days)
            log.info("scheduler.backfill_done", symbols=len(symbols), bars=total)
        except Exception as exc:  # noqa: BLE001 - a failed backfill must not kill the scheduler
            log.error("scheduler.backfill_failed", error=str(exc))
        finally:
            await provider.close()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(evaluate_alerts, "interval", seconds=settings.alert_interval_seconds)
    if settings.daily_backfill_enabled:
        scheduler.add_job(
            daily_backfill,
            "cron",
            hour=settings.daily_backfill_hour,
            minute=settings.daily_backfill_minute,
        )
    scheduler.start()
    log.info(
        "scheduler.started",
        alert_interval_s=settings.alert_interval_seconds,
        notify=settings.notify_channel,
        daily_backfill=settings.daily_backfill_enabled,
    )

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
