"""Provider contracts and the normalized schemas they emit; every bar/quote carries
``provider`` and ``feed`` provenance."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import date, datetime

from pydantic import BaseModel, Field


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


class MarketDataProvider(ABC):
    """Real-time + historical market data."""

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
    """One normalized, point-in-time XBRL fact. ``filed_at`` (when it became public)
    guards against look-ahead bias; history is append-only, a restatement is a new fact."""

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
    """Point-in-time fundamentals/filings."""

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
    """News and corporate-event adapter."""

    name: str
