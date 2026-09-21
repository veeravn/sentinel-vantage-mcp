"""ResearchService — per-strategy candidate ranking: combine market data with
point-in-time fundamentals, apply the strategy's hard gates, score the eligible universe
cross-sectionally, and return immutable results plus the excluded names."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.features.engine import compute_features
from sentinel_vantage.domain.research.engine import ResearchInputs, score_research
from sentinel_vantage.domain.research.gates import evaluate_research_gates
from sentinel_vantage.domain.research.models import (
    ResearchEligibility,
    ResearchResult,
)
from sentinel_vantage.domain.research.normalize import compute_fundamentals
from sentinel_vantage.domain.research.ports import FundamentalRepository
from sentinel_vantage.domain.research.strategy import StrategyProfile, get_strategy
from sentinel_vantage.domain.research.tags import ALL_TAGS
from sentinel_vantage.domain.trend.ports import BarRepository
from sentinel_vantage.providers.base import Bar

log = get_logger("research_service")

LOOKBACK_DAYS = 220
MOMENTUM_LOOKBACK = 126  # ~6 trading months
GATE_NO_FUNDAMENTALS = "GATE_NO_FUNDAMENTALS"


@runtime_checkable
class ResearchScoreRepository(Protocol):
    async def save_research_scores(self, results: Sequence[ResearchResult]) -> None: ...

    async def get_research_history(
        self, symbol: str, *, strategy: str, start: datetime, end: datetime
    ) -> list[ResearchResult]: ...


class RankResult(BaseModel):
    strategy: str
    as_of: datetime
    results: list[ResearchResult]
    ineligible: list[ResearchEligibility]
    universe_size: int


def _momentum(bars: Sequence[Bar], lookback: int = MOMENTUM_LOOKBACK) -> float | None:
    if len(bars) < 2:
        return None
    closes = [b.close for b in sorted(bars, key=lambda x: x.ts)]
    base = closes[-1 - lookback] if len(closes) > lookback else closes[0]
    return (closes[-1] / base - 1.0) if base else None


class ResearchService:
    def __init__(
        self,
        bars: BarRepository,
        fundamentals: FundamentalRepository,
        *,
        scores: ResearchScoreRepository | None = None,
    ) -> None:
        self.bars = bars
        self.fundamentals = fundamentals
        self.scores = scores

    async def _inputs(
        self, symbols: list[str], profile: StrategyProfile, as_of: datetime
    ) -> tuple[dict[str, ResearchInputs], list[ResearchEligibility]]:
        histories = await self.bars.get_daily_history(symbols, as_of, lookback_days=LOOKBACK_DAYS)
        eligible: dict[str, ResearchInputs] = {}
        ineligible: list[ResearchEligibility] = []

        for sym in symbols:
            bars = histories.get(sym, [])
            features = compute_features(sym, bars, as_of=as_of)
            cik = await self.fundamentals.cik_for(sym)
            if not cik:
                ineligible.append(
                    ResearchEligibility(
                        symbol=sym, eligible=False, hard_gate_failures=[GATE_NO_FUNDAMENTALS]
                    )
                )
                continue
            facts = await self.fundamentals.get_facts_asof(cik, ALL_TAGS, as_of.date())
            fund = compute_fundamentals(sym, cik, facts, price=features.last_price, as_of=as_of)
            elig = evaluate_research_gates(
                fund,
                price=features.last_price,
                dollar_volume_median_20d=features.dollar_volume_median_20d,
                profile=profile,
            )
            if elig.eligible:
                eligible[sym] = ResearchInputs(
                    fundamentals=fund,
                    momentum_6m=_momentum(bars),
                    realized_vol_20d=features.realized_vol_20d,
                    return_1d=features.return_1d,
                )
            else:
                ineligible.append(elig)
        return eligible, ineligible

    async def rank(
        self,
        strategy: str,
        *,
        as_of: datetime,
        universe: list[str] | None = None,
        sector: str | None = None,
        limit: int = 20,
        min_confidence: float = 0.0,
        persist: bool = False,
    ) -> RankResult:
        profile = get_strategy(strategy)
        symbols = universe or await self.bars.list_active_universe(as_of, sector=sector)
        inputs, ineligible = await self._inputs(symbols, profile, as_of)
        results = score_research(inputs, profile=profile, as_of=as_of)

        if persist and self.scores is not None:
            await self.scores.save_research_scores(results)

        shown = [r for r in results if r.confidence >= min_confidence][:limit]
        log.info(
            "research.rank",
            strategy=profile.id,
            universe=len(symbols),
            eligible=len(inputs),
            returned=len(shown),
        )
        return RankResult(
            strategy=profile.id,
            as_of=as_of,
            results=shown,
            ineligible=ineligible,
            universe_size=len(symbols),
        )

    async def compare(self, symbols: list[str], *, strategy: str, as_of: datetime) -> RankResult:
        """Score the given symbols cross-sectionally against each other."""
        profile = get_strategy(strategy)
        inputs, ineligible = await self._inputs(symbols, profile, as_of)
        results = score_research(inputs, profile=profile, as_of=as_of)
        return RankResult(
            strategy=profile.id,
            as_of=as_of,
            results=results,
            ineligible=ineligible,
            universe_size=len(symbols),
        )

    async def history(
        self, symbol: str, *, strategy: str, start: datetime, end: datetime
    ) -> list[ResearchResult]:
        if self.scores is None:
            return []
        profile = get_strategy(strategy)
        return await self.scores.get_research_history(
            symbol, strategy=profile.id, start=start, end=end
        )
