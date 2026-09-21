"""One-shot idempotent data load (``sv-bootstrap``): market bars, fundamentals, and filing
events, but only when the database is empty (a no-op on re-run unless SV_BOOTSTRAP_FORCE).
SEC steps are best-effort and skipped without SV_SEC_USER_AGENT."""

from __future__ import annotations

import asyncio
import os

from sentinel_vantage.apps.market_worker.backfill import _run as backfill_run
from sentinel_vantage.apps.market_worker.events_backfill import _run as events_run
from sentinel_vantage.apps.market_worker.fundamentals_backfill import _run as fundamentals_run
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.storage.postgres import Database

log = get_logger("bootstrap")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _already_loaded(db: Database) -> bool:
    return bool(await db.pool.fetchval("SELECT 1 FROM market_bar LIMIT 1"))


async def _run() -> None:
    settings = get_settings()
    force = _truthy(os.environ.get("SV_BOOTSTRAP_FORCE"))

    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        if not force and await _already_loaded(db):
            log.info(
                "bootstrap.skip",
                reason="market_bar already has data (set SV_BOOTSTRAP_FORCE=1 to reload)",
            )
            return
    finally:
        await db.close()

    log.info("bootstrap.start", force=force)
    await backfill_run(settings)

    if "set SV_SEC_USER_AGENT" in settings.sec_user_agent:
        log.warning("bootstrap.sec_skipped", reason="SV_SEC_USER_AGENT not set")
    else:
        for name, runner in (("fundamentals", fundamentals_run), ("events", events_run)):
            try:
                await runner(settings)
            except Exception as exc:  # noqa: BLE001 - best-effort; don't fail the whole load
                log.warning("bootstrap.step_failed", step=name, error=str(exc))
    log.info("bootstrap.done")


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
