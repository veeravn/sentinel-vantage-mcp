"""Provider contracts and the normalized event schemas they emit.

These mirror the interfaces in the design (section 8). Every normalized bar/quote
carries ``provider`` and ``feed`` provenance so downstream storage and scores can
record exactly where the number came from. Concrete adapters (Polygon, SEC, news)
implement these in later phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import date, datetime

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


class FundamentalFact(BaseModel):
    """One normalized, point-in-time XBRL fact.

    ``filed_at`` is the instant the fact became public — the guard against look-ahead
    bias. History is append-only: a restated value is a new fact with a later
    ``filed_at``, never an overwrite (design sections 8.2, 13, 17).
    """

    cik: str
    taxonomy: str = "us-gaap"
    tag: str = Field(description="XBRL concept, e.g. 'Revenues', 'NetIncomeLoss'.")
    unit: str = Field(description="e.g. 'USD', 'USD/shares', 'shares'.")
    value: float
    period_start: date | None = None
    period_end: date
    fy: int | None = None
    fp: str | None = Field(default=None, description="Fiscal period: FY, Q1..Q4.")
    form: str | None = Field(default=None, description="Filing form, e.g. '10-K', '10-Q'.")
    filed_at: date = Field(description="Date the filing was submitted (point-in-time key).")
    frame: str | None = None
    source: str = "SEC-XBRL"


class FundamentalsProvider(ABC):
    """Point-in-time fundamentals/filings (design section 8.2)."""

    name: str

    @abstractmethod
    async def get_cik_map(self) -> dict[str, str]:
        """Map upper-case ticker -> zero-padded 10-digit CIK."""
        raise NotImplementedError

    @abstractmethod
    async def get_facts(self, cik: str, tags: Iterable[str]) -> list[FundamentalFact]:
        """All point-in-time facts for the requested concept tags."""
        raise NotImplementedError


class NewsProvider(ABC):
    """News and corporate-event adapter (design section 8.3). Phase 3."""

    name: str
