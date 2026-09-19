"""Lightweight SQL-file migration runner.

Applies numbered ``*.sql`` files from ``migrations/`` in order, each in its own
transaction, recording applied versions in ``schema_migrations``. No ORM — we use raw
asyncpg, so a plain forward-only runner is the right amount of machinery. Re-running is
safe: already-applied files are skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg

from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
log = get_logger("migrate")


async def apply_migrations(dsn: str) -> list[str]:
    """Apply pending migrations; return the versions newly applied."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        newly: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", version)
            log.info("migrate.applied", version=version)
            newly.append(version)
        if not newly:
            log.info("migrate.up_to_date")
        return newly
    finally:
        await conn.close()


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(apply_migrations(settings.postgres_dsn))


if __name__ == "__main__":
    main()
