"""Postgres access: open a connection pool and answer a health ping. Kept thin."""

from __future__ import annotations

import asyncpg

from sentinel_vantage.core.logging import get_logger

log = get_logger(__name__)


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=10)
            log.info("postgres.connected")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("postgres.closed")

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() must be called before use.")
        return self._pool

    async def ping(self) -> bool:
        """Return True if a trivial query succeeds. Never raises."""
        try:
            if self._pool is None:
                conn = await asyncpg.connect(self._dsn)
                try:
                    await conn.fetchval("SELECT 1")
                finally:
                    await conn.close()
            else:
                await self._pool.fetchval("SELECT 1")
            return True
        except Exception as exc:  # noqa: BLE001 - health checks must not propagate
            log.warning("postgres.ping_failed", error=str(exc))
            return False
