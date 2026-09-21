"""Redis research rank cache the worker publishes each cycle, one entry per strategy, so
find_research_candidates can serve a warm read. Keys: ``rank:research:{strategy}`` (sorted
set) and ``latest:research:{strategy}:{symbol}`` (JSON)."""

from __future__ import annotations

from collections.abc import Sequence

from sentinel_vantage.domain.research.models import ResearchResult
from sentinel_vantage.storage.redis_store import RedisStore


def _rank_key(strategy: str) -> str:
    return f"rank:research:{strategy}"


def _latest_key(strategy: str, symbol: str) -> str:
    return f"latest:research:{strategy}:{symbol}"


class RedisResearchRankCache:
    def __init__(self, redis: RedisStore) -> None:
        self._redis = redis

    async def publish(self, strategy: str, results: Sequence[ResearchResult]) -> None:
        """Replace the rank set for a strategy and refresh latest-score entries."""
        if not results:
            return
        client = self._redis.client
        pipe = client.pipeline(transaction=True)
        pipe.delete(_rank_key(strategy))
        pipe.zadd(_rank_key(strategy), {r.symbol: r.score for r in results})
        for r in results:
            pipe.set(_latest_key(strategy, r.symbol), r.model_dump_json())
        await pipe.execute()

    async def top(self, strategy: str, limit: int = 20) -> list[ResearchResult]:
        """Return the top-N latest results for a strategy by score (highest first)."""
        client = self._redis.client
        symbols = await client.zrevrange(_rank_key(strategy), 0, max(0, limit - 1))
        if not symbols:
            return []
        raw = await client.mget([_latest_key(strategy, s) for s in symbols])
        return [ResearchResult.model_validate_json(v) for v in raw if v]

    async def latest(self, strategy: str, symbol: str) -> ResearchResult | None:
        raw = await self._redis.client.get(_latest_key(strategy, symbol))
        return ResearchResult.model_validate_json(raw) if raw else None
