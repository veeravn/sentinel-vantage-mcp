"""Provider contracts and the normalized event schemas they emit.

These mirror the interfaces in the design (section 8). Every normalized bar/quote
carries ``provider`` and ``feed`` provenance so downstream storage and scores can
record exactly where the number came from. Concrete adapters (Polygon, SEC, news)
implement these in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Normalized market-data schemas
# --------------------------------------------------------------------------- #
class Bar(BaseModel):
    symbol: str
    ts: datetime = Field(description="UTC start of the bar interval.")
    timeframe: str = Field(description="e.g. '1m', '1d'.")
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    feed: str = Field(description="Feed provenance, e.g. 'polygon/delayed'.")


class BarEvent(BaseModel):
    """A single bar delivered over a live stream."""

    bar: Bar
    received_at: datetime


class Quote(BaseModel):
    symbol: str
    ts: datetime
    bid: float | None = None
    ask: float | None = None
    provider: str
    feed: str


class Session(BaseModel):
    """One market-calendar trading session."""

    date: str = Field(description="YYYY-MM-DD in exchange local date.")
    open: datetime
    close: datetime
    is_open: bool = True


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #
class MarketDataProvider(ABC):
    """Real-time + historical market data (design section 8.1)."""

    name: str

    @abstractmethod
    def stream_bars(self, symbols: Sequence[str] | str) -> AsyncIterator[BarEvent]:
        """Live bar stream. Pass '*' for the full subscribed universe."""
        raise NotImplementedError

    @abstractmethod
    async def get_bars(
        self, symbols: Sequence[str], timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        """Historical bars for backfill and baselines."""
        raise NotImplementedError

    @abstractmethod
    async def get_latest_quotes(self, symbols: Sequence[str]) -> list[Quote]:
        raise NotImplementedError

    @abstractmethod
    async def get_market_calendar(self, start: datetime, end: datetime) -> list[Session]:
        raise NotImplementedError


class FundamentalsProvider(ABC):
    """Point-in-time fundamentals/filings (design section 8.2). Phase 2."""

    name: str


class NewsProvider(ABC):
    """News and corporate-event adapter (design section 8.3). Phase 3."""

    name: str
