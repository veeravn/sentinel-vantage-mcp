"""Entrypoint: run a point-in-time backtest of a model over stored data.

Usage: sv-backtest [trend|garp] [--horizon N] [--every N] [--buckets N]
                   [--min-confidence F]
"""

from __future__ import annotations

import argparse
import asyncio

from sentinel_vantage.backtest.models import BacktestReport
from sentinel_vantage.backtest.runner import run_research_backtest, run_trend_backtest
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import PostgresFundamentalRepository


def _print_report(report: BacktestReport) -> None:
    print(
        f"\nBacktest: {report.strategy}  horizon={report.horizon_days}d  "
        f"buckets={report.n_buckets}  rebalances={len(report.rebalances)}"
    )
    print(
        f"coverage={report.coverage:.2f}  "
        f"mean rank IC={_fmt(report.mean_rank_ic)}  "
        f"hit rate(top>bottom)={_fmt(report.hit_rate_top_gt_bottom)}  "
        f"top-bucket turnover={_fmt(report.avg_turnover_top_bucket)}"
    )
    print("\nforward return by score bucket (low -> high):")
    for b, ret in enumerate(report.mean_bucket_returns):
        bar = "#" * max(0, int(ret * 500))
        print(f"  bucket {b}: {ret * 100:+7.2f}%  {bar}")
    print(f"\ntop-minus-bottom spread: {_fmt_pct(report.mean_top_minus_bottom)}")
    if report.mean_rank_ic is not None and report.mean_rank_ic > 0.03:
        print("→ positive rank IC: higher scores tended to precede higher forward returns.")
    elif report.rebalances:
        print("→ weak/negative signal on this sample (expected with few names / short history).")


def _fmt(v: float | None) -> str:
    return f"{v:.3f}" if v is not None else "n/a"


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:+.2f}%" if v is not None else "n/a"


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = Database(settings.postgres_dsn)
    await db.connect()
    try:
        rows = await db.pool.fetch(
            "SELECT symbol FROM security WHERE is_benchmark = FALSE ORDER BY symbol"
        )
        symbols = [r["symbol"] for r in rows]
        if args.model == "trend":
            report = await run_trend_backtest(
                db,
                symbols,
                horizon=args.horizon,
                every=args.every,
                n_buckets=args.buckets,
                min_confidence=args.min_confidence,
            )
        else:
            report = await run_research_backtest(
                db,
                symbols,
                PostgresFundamentalRepository(db),
                strategy=args.model,
                horizon=args.horizon,
                every=args.every,
                n_buckets=args.buckets,
                min_confidence=args.min_confidence,
            )
        _print_report(report)
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="sv-backtest")
    parser.add_argument(
        "model",
        nargs="?",
        default="trend",
        help="'trend' or a research strategy id/name (e.g. 'garp')",
    )
    parser.add_argument("--horizon", type=int, default=20, help="holding period in trading days")
    parser.add_argument("--every", type=int, default=5, help="rebalance spacing in trading days")
    parser.add_argument("--buckets", type=int, default=5)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    args = parser.parse_args()

    settings = get_settings()
    # Quiet per-rebalance service logs; the report is the output.
    configure_logging(level="WARNING", json=settings.environment == "production")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
