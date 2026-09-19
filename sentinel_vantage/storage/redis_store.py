"""Redis access.

Phase 0 provides connect/close/ping. Later phases add the latest-score and rank
sorted-set helpers (rank:trend:{horizon}, latest:trend:{symbol}:{horizon}, ...).
Module is named ``redis_store`` to avoid shadowing the ``redis`` package.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from sentinel_vantage.core.logging import get_logger

log = get_logger(__name__)


class RedisStore:
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
            log.info("redis.connected")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            log.info("redis.closed")

    @property
    def client(self) -> aioredis.Redis:
        if self._client is None:
            raise RuntimeError("RedisStore.connect() must be called before use.")
        return self._client

    async def ping(self) -> bool:
        """Return True if the server responds to PING. Never raises."""
        try:
            if self._client is None:
                client = aioredis.from_url(self._url, decode_responses=True)
                try:
                    return bool(await client.ping())
                finally:
                    await client.aclose()
            return bool(await self._client.ping())
        except Exception as exc:  # noqa: BLE001 - health checks must not propagate
            log.warning("redis.ping_failed", error=str(exc))
            return False
