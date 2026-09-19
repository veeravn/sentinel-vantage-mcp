"""Redis latest-score and rank cache.

The worker publishes each scoring cycle here so the query path can answer trending
scans in well under a second without recomputing (design NFR: <2s scans). Keys follow
the design's illustrative scheme:

    rank:trend:{horizon}              sorted set, score -> symbol
    latest:trend:{symbol}:{horizon}   JSON of the latest TrendResult
"""

from __future__ import annotations

from collections.abc import Sequence

from sentinel_vantage.domain.trend.models import TrendResult
from sentinel_vantage.storage.redis_store import RedisStore


def _rank_key(horizon: str) -> str:
    return f"rank:trend:{horizon}"


def _latest_key(symbol: str, horizon: str) -> str:
    return f"latest:trend:{symbol}:{horizon}"


class RedisRankCache:
    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    async def publish(self, horizon: str, results: Sequence[TrendResult]) -> None:
        """Replace the rank set for a horizon and refresh latest-score entries."""
        if not results:
            return
        client = self._redis.client
        pipe = client.pipeline(transaction=True)
        pipe.delete(_rank_key(horizon))
        mapping = {r.symbol: r.score for r in results}
        pipe.zadd(_rank_key(horizon), mapping)
        for r in results:
            pipe.set(_latest_key(r.symbol, horizon), r.model_dump_json())
        await pipe.execute()

    async def top(self, horizon: str, limit: int = 20) -> list[TrendResult]:
        """Return the top-N latest results by score (highest first)."""
        client = self._redis.client
        symbols = await client.zrevrange(_rank_key(horizon), 0, max(0, limit - 1))
        if not symbols:
            return []
        raw = await client.mget([_latest_key(s, horizon) for s in symbols])
        return [TrendResult.model_validate_json(v) for v in raw if v]

    async def latest(self, symbol: str, horizon: str) -> TrendResult | None:
        raw = await self._redis.client.get(_latest_key(symbol, horizon))
        return TrendResult.model_validate_json(raw) if raw else None
