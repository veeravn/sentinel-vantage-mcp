"""TrendService — orchestrates the trend pipeline: fetch history via the BarRepository
port, compute features, apply gates, score the eligible universe cross-sectionally, and
return immutable results plus the excluded symbols."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.versioning import FEATURE_SET_VERSION
from sentinel_vantage.domain.features.engine import compute_features
from sentinel_vantage.domain.features.models import FeatureSet
from sentinel_vantage.domain.features.ports import FeatureRepository
from sentinel_vantage.domain.trend.gates import DEFAULT_GATES, TrendGateConfig, evaluate_gates
from sentinel_vantage.domain.trend.models import Eligibility, TrendResult
from sentinel_vantage.domain.trend.ports import BarRepository, ScoreRepository
from sentinel_vantage.domain.trend.scoring import (
    DEFAULT_SCORING,
    TrendScoringConfig,
    score_universe,
)

log = get_logger("trend_service")

# Daily bars pulled per symbol for feature computation (covers 60-120d history + baselines).
DEFAULT_LOOKBACK_DAYS = 130


class ScanResult(BaseModel):
    horizon: str
    as_of: datetime
    results: list[TrendResult]
    ineligible: list[Eligibility]
    universe_size: int


class StockAnalysis(BaseModel):
    symbol: str
    horizon: str
    as_of: datetime
    eligible: bool
    gate_failures: list[str]
    result: TrendResult | None = None


class TrendService:
    def __init__(
        self,
        bars: BarRepository,
        *,
        scores: ScoreRepository | None = None,
        features: FeatureRepository | None = None,
        gate_config: TrendGateConfig = DEFAULT_GATES,
        scoring_config: TrendScoringConfig = DEFAULT_SCORING,
    ) -> None:
        self.bars = bars
        self.scores = scores
        self.features = features
        self.gate_config = gate_config
        self.scoring_config = scoring_config

    async def _eligible_features(
        self, symbols: list[str], as_of: datetime
    ) -> tuple[dict[str, FeatureSet], list[Eligibility]]:
        histories = await self.bars.get_daily_history(
            symbols, as_of, lookback_days=DEFAULT_LOOKBACK_DAYS
        )
        bench = histories.get(self.bars.benchmark_symbol)
        if bench is None:
            bench = (
                await self.bars.get_daily_history(
                    [self.bars.benchmark_symbol], as_of, lookback_days=DEFAULT_LOOKBACK_DAYS
                )
            ).get(self.bars.benchmark_symbol)

        eligible: dict[str, FeatureSet] = {}
        ineligible: list[Eligibility] = []
        for sym in symbols:
            if sym == self.bars.benchmark_symbol:
                continue
            fs = compute_features(sym, histories.get(sym, []), as_of=as_of, benchmark_bars=bench)
            is_active = await self.bars.is_active(sym, as_of)
            elig = evaluate_gates(fs, is_active=is_active, config=self.gate_config)
            if elig.eligible:
                eligible[sym] = fs
            else:
                ineligible.append(elig)
        return eligible, ineligible

    async def scan(
        self,
        *,
        as_of: datetime,
        horizon: str = "1d",
        universe: list[str] | None = None,
        sector: str | None = None,
        limit: int = 20,
        min_confidence: float = 0.0,
        persist: bool = False,
    ) -> ScanResult:
        symbols = universe or await self.bars.list_active_universe(as_of, sector=sector)
        eligible, ineligible = await self._eligible_features(symbols, as_of)
        results = score_universe(eligible, horizon=horizon, as_of=as_of, config=self.scoring_config)

        if persist:
            # Persist feature inputs first so every stored score is reconstructable.
            if self.features is not None:
                await self.features.save_feature_snapshots(
                    list(eligible.values()), feature_set_version=FEATURE_SET_VERSION
                )
            if self.scores is not None:
                await self.scores.save_trend_scores(results)

        shown = [r for r in results if r.confidence >= min_confidence][:limit]
        log.info(
            "trend.scan",
            universe=len(symbols),
            eligible=len(eligible),
            returned=len(shown),
            horizon=horizon,
        )
        return ScanResult(
            horizon=horizon,
            as_of=as_of,
            results=shown,
            ineligible=ineligible,
            universe_size=len(symbols),
        )

    async def analyze(self, symbol: str, *, as_of: datetime, horizon: str = "1d") -> StockAnalysis:
        """Full evidence for one symbol, scored in the context of the current universe."""
        universe = await self.bars.list_active_universe(as_of)
        if symbol not in universe:
            universe = [*universe, symbol]
        scan = await self.scan(as_of=as_of, horizon=horizon, universe=universe, limit=len(universe))

        for r in scan.results:
            if r.symbol == symbol:
                return StockAnalysis(
                    symbol=symbol,
                    horizon=horizon,
                    as_of=as_of,
                    eligible=True,
                    gate_failures=[],
                    result=r,
                )
        failures = next(
            (e.gate_failures for e in scan.ineligible if e.symbol == symbol), ["SYMBOL_NOT_FOUND"]
        )
        return StockAnalysis(
            symbol=symbol,
            horizon=horizon,
            as_of=as_of,
            eligible=False,
            gate_failures=failures,
        )

    async def score_history(
        self, symbol: str, *, horizon: str, start: datetime, end: datetime
    ) -> list[TrendResult]:
        if self.scores is None:
            return []
        return await self.scores.get_trend_history(symbol, horizon=horizon, start=start, end=end)
