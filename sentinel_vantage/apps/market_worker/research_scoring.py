"""One research scoring cycle: for each configured strategy, score the eligible universe,
persist the score snapshots, and publish the per-strategy ranks to the Redis cache."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.research.service import RankResult, ResearchService
from sentinel_vantage.storage.research_rank_cache import RedisResearchRankCache

log = get_logger("research_scoring")

# Score the whole eligible set; the query layer truncates to top-N at read time.
_ALL = 1_000_000


async def run_research_cycle(
    research: ResearchService,
    cache: RedisResearchRankCache | None,
    *,
    strategies: Sequence[str],
    as_of: datetime,
) -> dict[str, RankResult]:
    """Score and persist each strategy; a bad strategy name never kills the cycle."""
    out: dict[str, RankResult] = {}
    for strategy in strategies:
        try:
            rank = await research.rank(strategy, as_of=as_of, limit=_ALL, persist=True)
        except Exception as exc:  # noqa: BLE001 - one bad strategy must not stop the rest
            log.error("research.cycle_failed", strategy=strategy, error=str(exc))
            continue
        if cache is not None:
            await cache.publish(rank.strategy, rank.results)
        out[rank.strategy] = rank
        log.info(
            "research.cycle",
            strategy=rank.strategy,
            as_of=as_of.isoformat(),
            scored=len(rank.results),
            ineligible=len(rank.ineligible),
        )
    return out
