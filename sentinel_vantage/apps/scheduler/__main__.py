"""Entrypoint: run the scheduler process.

Phase 0 stands up an APScheduler event loop with no jobs registered yet — proving the
process runs independently. Phase 5 registers alert-evaluation and briefing jobs.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger


async def _run() -> None:
    log = get_logger("scheduler")
    scheduler = AsyncIOScheduler()
    # Phase 5: scheduler.add_job(evaluate_alert_rules, "interval", minutes=1), etc.
    scheduler.start()
    log.info("scheduler.started", jobs=len(scheduler.get_jobs()))
    stop = asyncio.Event()
    try:
        await stop.wait()  # run until the container/process is signalled to stop
    finally:
        scheduler.shutdown(wait=False)
        log.info("scheduler.stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
