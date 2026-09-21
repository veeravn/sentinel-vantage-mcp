"""Strategy-agnostic, point-in-time backtest engine: on each rebalance date it scores via
``score_fn``, measures forward returns, buckets by score, and aggregates the evaluation
metrics. Look-ahead safety is the caller's ``score_fn``/``forward_return_fn`` duty."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from sentinel_vantage.backtest.metrics import assign_buckets, spearman
from sentinel_vantage.backtest.models import BacktestReport, BucketStat, RebalanceResult
from sentinel_vantage.core.logging import get_logger

log = get_logger("backtest")

# as_of -> {symbol: score} using only point-in-time data.
ScoreFn = Callable[[datetime], Awaitable[dict[str, float]]]
# (symbol, as_of) -> forward return over the holding horizon, or None if unavailable.
ForwardReturnFn = Callable[[str, datetime], Awaitable[float | None]]


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


async def run_backtest(
    *,
    strategy: str,
    rebalance_dates: Sequence[datetime],
    score_fn: ScoreFn,
    forward_return_fn: ForwardReturnFn,
    horizon_days: int,
    n_buckets: int = 5,
    universe_size: int | None = None,
) -> BacktestReport:
    rebalances: list[RebalanceResult] = []
    turnovers: list[float] = []
    coverages: list[float] = []
    prev_top: set[str] = set()

    for as_of in rebalance_dates:
        scores = await score_fn(as_of)
        triples: list[tuple[str, float, float]] = []
        for symbol in sorted(scores):
            fr = await forward_return_fn(symbol, as_of)
            if fr is not None:
                triples.append((symbol, scores[symbol], fr))

        if universe_size:
            coverages.append(len(triples) / universe_size)

        if len(triples) < n_buckets:
            log.info("backtest.skip_date", as_of=as_of.isoformat(), scored=len(triples))
            continue

        buckets = assign_buckets([(s, sc) for s, sc, _ in triples], n_buckets)
        by_bucket: dict[int, list[float]] = defaultdict(list)
        for symbol, _, fr in triples:
            by_bucket[buckets[symbol]].append(fr)

        bstats = [
            BucketStat(
                bucket=b,
                count=len(by_bucket.get(b, [])),
                mean_forward_return=round(_mean(by_bucket.get(b, [])) or 0.0, 6),
            )
            for b in range(n_buckets)
        ]
        tmb = round(bstats[-1].mean_forward_return - bstats[0].mean_forward_return, 6)
        ic = spearman([sc for _, sc, _ in triples], [fr for _, _, fr in triples])

        top_names = {s for s, _, _ in triples if buckets[s] == n_buckets - 1}
        if prev_top and top_names:
            turnovers.append(1.0 - len(top_names & prev_top) / len(top_names))
        prev_top = top_names

        rebalances.append(
            RebalanceResult(
                as_of=as_of,
                n_scored=len(triples),
                buckets=bstats,
                top_minus_bottom=tmb,
                rank_ic=round(ic, 6) if ic is not None else None,
            )
        )

    return _aggregate(strategy, horizon_days, n_buckets, rebalances, turnovers, coverages)


def _aggregate(
    strategy: str,
    horizon_days: int,
    n_buckets: int,
    rebalances: list[RebalanceResult],
    turnovers: list[float],
    coverages: list[float],
) -> BacktestReport:
    mean_bucket_returns: list[float] = []
    for b in range(n_buckets):
        vals = [r.buckets[b].mean_forward_return for r in rebalances]
        mean_bucket_returns.append(round(_mean(vals) or 0.0, 6))

    tmbs = [r.top_minus_bottom for r in rebalances if r.top_minus_bottom is not None]
    ics = [r.rank_ic for r in rebalances if r.rank_ic is not None]
    hit = _mean([1.0 if v > 0 else 0.0 for v in tmbs]) if tmbs else None

    return BacktestReport(
        strategy=strategy,
        horizon_days=horizon_days,
        n_buckets=n_buckets,
        rebalances=rebalances,
        mean_bucket_returns=mean_bucket_returns,
        mean_top_minus_bottom=round(_mean(tmbs), 6) if tmbs else None,
        hit_rate_top_gt_bottom=round(hit, 6) if hit is not None else None,
        mean_rank_ic=round(_mean(ics), 6) if ics else None,
        avg_turnover_top_bucket=round(_mean(turnovers), 6) if turnovers else None,
        coverage=round(_mean(coverages) or 0.0, 6),
    )
