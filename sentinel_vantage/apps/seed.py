"""Entrypoint: seed the reference universe into Postgres (idempotent)."""

from __future__ import annotations

import asyncio

from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging
from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.storage.postgres import Database


async def _run() -> None:
    settings = get_settings()
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        await seed_universe(db)
    finally:
        await db.close()


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
