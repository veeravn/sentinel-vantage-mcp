"""Shared test fixtures: deterministic synthetic bar builders, plus the guarded connection
settings for DB integration tests.

DB tests TRUNCATE tables and flush Redis, so they never read SV_POSTGRES_DSN / SV_REDIS_URL
(your dev data). They use SV_TEST_POSTGRES_DSN / SV_TEST_REDIS_URL and refuse to run unless
the database name ends in ``_test`` and the Redis DB index is not 0.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import pytest

from sentinel_vantage.providers.base import Bar

DB_TESTS_ENABLED = os.environ.get("SV_RUN_DB_TESTS") == "1"
TEST_PG_DSN = os.environ.get(
    "SV_TEST_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel_test"
)
TEST_REDIS_URL = os.environ.get("SV_TEST_REDIS_URL", "redis://localhost:6379/15")


def _check_test_targets() -> None:
    db_name = urlparse(TEST_PG_DSN).path.lstrip("/")
    if not db_name.endswith("_test"):
        raise pytest.UsageError(
            f"refusing to run DB tests: database '{db_name}' must end in '_test' "
            "(these tests TRUNCATE tables). Set SV_TEST_POSTGRES_DSN."
        )
    redis_db = urlparse(TEST_REDIS_URL).path.lstrip("/") or "0"
    if redis_db == "0":
        raise pytest.UsageError(
            "refusing to run DB tests: Redis DB 0 is flushed by tests; "
            "use another index via SV_TEST_REDIS_URL (e.g. redis://localhost:6379/15)."
        )


async def _ensure_test_database() -> None:
    import asyncpg

    parsed = urlparse(TEST_PG_DSN)
    name = parsed.path.lstrip("/")
    conn = await asyncpg.connect(parsed._replace(path="/postgres").geturl())
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


if DB_TESTS_ENABLED:
    _check_test_targets()


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> None:
    if DB_TESTS_ENABLED:
        asyncio.run(_ensure_test_database())


def make_daily_bars(
    symbol: str,
    closes: list[float],
    volumes: list[float] | None = None,
    *,
    start: str = "2026-03-02",
    provider: str = "test",
    feed: str = "test/fixture",
) -> list[Bar]:
    """Build consecutive daily bars from a close series (open = previous close)."""
    if volumes is None:
        volumes = [1_000_000.0] * len(closes)
    assert len(closes) == len(volumes)

    d0 = datetime.fromisoformat(start).replace(tzinfo=UTC)
    bars: list[Bar] = []
    prev = closes[0]
    for i, (c, v) in enumerate(zip(closes, volumes, strict=True)):
        o = prev
        bars.append(
            Bar(
                symbol=symbol,
                ts=d0 + timedelta(days=i),
                timeframe="1d",
                open=o,
                high=max(o, c) * 1.01,
                low=min(o, c) * 0.99,
                close=c,
                volume=v,
                provider=provider,
                feed=feed,
            )
        )
        prev = c
    return bars


def flat_series(value: float, n: int) -> list[float]:
    return [value] * n


def as_of_of(bars: list[Bar]) -> datetime:
    return bars[-1].ts
