"""One worker scoring cycle: score every eligible symbol, persist feature and score
snapshots, and publish the full ranked set to the Redis cache the query path reads."""

from __future__ import annotations

from datetime import datetime

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.trend.service import ScanResult, TrendService
from sentinel_vantage.storage.rank_cache import RedisRankCache

log = get_logger("scoring")

# Score the whole eligible set; the query layer truncates to top-N at read time.
_ALL = 1_000_000


async def run_scoring_cycle(
    service: TrendService,
    rank_cache: RedisRankCache | None,
    *,
    horizon: str,
    as_of: datetime,
) -> ScanResult:
    scan = await service.scan(as_of=as_of, horizon=horizon, limit=_ALL, persist=True)
    if rank_cache is not None:
        await rank_cache.publish(horizon, scan.results)
    log.info(
        "scoring.cycle",
        horizon=horizon,
        as_of=as_of.isoformat(),
        scored=len(scan.results),
        ineligible=len(scan.ineligible),
    )
    return scan
