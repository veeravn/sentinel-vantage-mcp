"""Ports the research engine depends on for fundamentals access."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from sentinel_vantage.providers.base import FundamentalFact


@runtime_checkable
class FundamentalRepository(Protocol):
    async def cik_for(self, symbol: str) -> str | None: ...

    async def get_facts_asof(
        self, cik: str, tags: Sequence[str], as_of: date
    ) -> list[FundamentalFact]:
        """Facts for the tags visible as of a date (filed_at <= as_of) — point-in-time."""
        ...
