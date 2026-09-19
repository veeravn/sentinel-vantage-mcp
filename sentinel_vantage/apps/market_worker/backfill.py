"""Historical backfill: pull daily bars from the provider into Postgres.

Entry point ``sv-backfill`` seeds the universe (idempotent), then fetches daily bars for
every active symbol plus the benchmark over a trailing window and upserts them. MVP
ingests provider-adjusted bars (corporate actions applied upstream); adj_close is left
NULL, reserved for a future raw+adjusted split.

For large universes prefer Polygon Flat Files over per-symbol REST — a later refinement.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sentinel_vantage.core.config import Settings, get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.domain.market.universe import active_symbols, benchmark_symbol, seed_universe
from sentinel_vantage.providers.base import Bar, MarketDataProvider
from sentinel_vantage.providers.market_data.polygon import PolygonMarketDataProvider
from sentinel_vantage.storage.postgres import Database

log = get_logger("backfill")


async def store_bars(db: Database, bars: list[Bar]) -> int:
    if not bars:
        return 0
    await db.pool.executemany(
        "INSERT INTO market_bar "
        "(symbol, ts, timeframe, open, high, low, close, volume, adj_close, provider, feed) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NULL,$9,$10) "
        "ON CONFLICT (symbol, timeframe, ts) DO NOTHING",
        [
            (
                b.symbol,
                b.ts,
                b.timeframe,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.provider,
                b.feed,
            )
            for b in bars
        ],
    )
    return len(bars)


async def backfill(
    db: Database,
    provider: MarketDataProvider,
    symbols: list[str],
    *,
    days: int,
    timeframe: str = "1d",
) -> int:
    end = utcnow()
    start = end - timedelta(days=days)
    total = 0
    for sym in symbols:
        bars = await provider.get_bars([sym], timeframe, start, end)
        total += await store_bars(db, bars)
        log.info("backfill.symbol", symbol=sym, bars=len(bars))
    return total


async def _run(settings: Settings) -> None:
    db = Database(settings.postgres_dsn)
    await db.connect()
    provider = PolygonMarketDataProvider(
        settings.polygon_api_key,
        feed_mode=settings.feed_mode,
        requests_per_minute=settings.polygon_requests_per_minute,
    )
    try:
        await seed_universe(db)
        symbols = [benchmark_symbol(), *active_symbols()]
        total = await backfill(db, provider, symbols, days=settings.backfill_days)
        log.info("backfill.done", symbols=len(symbols), bars=total)
    finally:
        await provider.close()
        await db.close()


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    if not settings.polygon_api_key:
        raise SystemExit("SV_POLYGON_API_KEY is not set; cannot backfill.")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
