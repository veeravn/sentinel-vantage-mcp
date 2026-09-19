"""Point-in-time fundamentals storage (gated by SV_RUN_DB_TESTS)."""

from __future__ import annotations

import os
from datetime import date

import pytest

from sentinel_vantage.domain.market.universe import seed_universe
from sentinel_vantage.providers.base import FundamentalFact
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import PostgresFundamentalRepository

PG_DSN = os.environ.get("SV_POSTGRES_DSN", "postgresql://sentinel:sentinel@localhost:5432/sentinel")

pytestmark = pytest.mark.skipif(
    os.environ.get("SV_RUN_DB_TESTS") != "1", reason="set SV_RUN_DB_TESTS=1 to run DB tests"
)


@pytest.fixture
async def db():
    from sentinel_vantage.storage.migrate import apply_migrations

    await apply_migrations(PG_DSN)
    database = Database(PG_DSN)
    await database.connect()
    await database.pool.execute("TRUNCATE security, fundamental_fact")
    yield database
    await database.close()


def _fact(value, *, end, filed, tag="Revenues"):
    return FundamentalFact(
        cik="0000320193",
        tag=tag,
        unit="USD",
        value=value,
        period_start=date(end.year, 1, 1),
        period_end=end,
        fy=end.year,
        fp="FY",
        form="10-K",
        filed_at=filed,
    )


async def test_cik_link_and_point_in_time_reads(db):
    await seed_universe(db)
    repo = PostgresFundamentalRepository(db)
    await repo.set_cik("AAPL", "0000320193")
    assert await repo.cik_for("AAPL") == "0000320193"

    # Original filing and a later restatement of the SAME period (different filed_at).
    await repo.save_facts(
        [
            _fact(383_000_000_000, end=date(2023, 12, 31), filed=date(2024, 2, 1)),
            _fact(384_000_000_000, end=date(2023, 12, 31), filed=date(2024, 8, 1)),  # restatement
            _fact(365_000_000_000, end=date(2022, 12, 31), filed=date(2023, 2, 1)),
        ]
    )

    # As of just after the original 2023 filing: restatement not yet visible.
    early = await repo.get_facts_asof("0000320193", ["Revenues"], date(2024, 3, 1))
    ends = sorted({f.period_end for f in early})
    assert ends == [date(2022, 12, 31), date(2023, 12, 31)]
    fy2023 = [f for f in early if f.period_end == date(2023, 12, 31)]
    assert len(fy2023) == 1 and fy2023[0].value == 383_000_000_000  # pre-restatement value

    # After the restatement filing: both versions of FY2023 are visible (append-only).
    later = await repo.get_facts_asof("0000320193", ["Revenues"], date(2024, 9, 1))
    fy2023_later = sorted(
        (f for f in later if f.period_end == date(2023, 12, 31)), key=lambda f: f.filed_at
    )
    assert [f.value for f in fy2023_later] == [383_000_000_000, 384_000_000_000]

    # Idempotent re-save: unique index prevents duplicates.
    await repo.save_facts([_fact(383_000_000_000, end=date(2023, 12, 31), filed=date(2024, 2, 1))])
    again = await repo.get_facts_asof("0000320193", ["Revenues"], date(2024, 3, 1))
    assert len(again) == len(early)
