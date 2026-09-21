"""Universe management: seed and reconcile the ``security`` reference table."""

from __future__ import annotations

from collections.abc import Sequence

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.market.seed_data import SEED_SECURITIES, SeedSecurity
from sentinel_vantage.storage.postgres import Database

log = get_logger("universe")


async def seed_universe(db: Database, securities: Sequence[SeedSecurity] = SEED_SECURITIES) -> int:
    """Upsert reference securities (idempotent; returns the number written). Delisting is
    recorded by setting ``active_to``, never by deleting the row."""
    rows = [
        (
            s["symbol"],
            s.get("name"),
            s.get("sector"),
            bool(s.get("is_etf", False)),
            bool(s.get("is_benchmark", False)),
        )
        for s in securities
    ]
    await db.pool.executemany(
        "INSERT INTO security (symbol, name, sector, is_etf, is_benchmark) "
        "VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (symbol) DO UPDATE SET "
        "  name = EXCLUDED.name, sector = EXCLUDED.sector, "
        "  is_etf = EXCLUDED.is_etf, is_benchmark = EXCLUDED.is_benchmark, "
        "  updated_at = now()",
        rows,
    )
    log.info("universe.seeded", count=len(rows))
    return len(rows)


def active_symbols(securities: Sequence[SeedSecurity] = SEED_SECURITIES) -> list[str]:
    """Non-benchmark symbols in a seed set (handy for backfill/CLI)."""
    return [s["symbol"] for s in securities if not s.get("is_benchmark")]


def benchmark_symbol(securities: Sequence[SeedSecurity] = SEED_SECURITIES) -> str:
    return next((s["symbol"] for s in securities if s.get("is_benchmark")), "SPY")
