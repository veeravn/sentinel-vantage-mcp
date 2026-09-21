"""Strategy profiles: versioned, immutable YAML config (universe/hard gates, factor
weights, penalties). A version that has produced a persisted score is frozen — a weight
change is a new ``score_version``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Packaged inside sentinel_vantage/ (like the SQL migrations) so it ships in the wheel/image.
STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "strategies"


class UniverseGates(BaseModel):
    min_price: float = 3.0
    min_median_dollar_volume_20d: float = 10_000_000.0


class HardGates(BaseModel):
    revenue_growth_yoy_min: float | None = None
    data_confidence_min: float = 0.8


class Penalties(BaseModel):
    extreme_volatility: float = 0.0
    extreme_short_term_move: float = 0.0
    leverage: float = 0.0


class PenaltyThresholds(BaseModel):
    extreme_volatility_20d: float = 0.05
    extreme_short_term_move_1d: float = 0.15
    leverage_debt_to_equity: float = 2.0


class StrategyProfile(BaseModel):
    id: str
    name: str
    universe: UniverseGates = Field(default_factory=UniverseGates)
    hard_gates: HardGates = Field(default_factory=HardGates)
    weights: dict[str, float]
    penalties: Penalties = Field(default_factory=Penalties)
    thresholds: PenaltyThresholds = Field(default_factory=PenaltyThresholds)
    score_version: str


def load_strategy_file(path: Path) -> StrategyProfile:
    return StrategyProfile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def load_strategies(directory: Path = STRATEGIES_DIR) -> dict[str, StrategyProfile]:
    """Load all strategy YAMLs, keyed by both id and lower-cased name."""
    out: dict[str, StrategyProfile] = {}
    for path in sorted(directory.glob("*.yaml")):
        profile = load_strategy_file(path)
        out[profile.id] = profile
        out[profile.name.lower()] = profile
    return out


def get_strategy(name_or_id: str, directory: Path = STRATEGIES_DIR) -> StrategyProfile:
    strategies = load_strategies(directory)
    key = name_or_id.lower()
    if key not in strategies:
        available = sorted({p.id for p in strategies.values()})
        raise KeyError(f"Unknown strategy {name_or_id!r}. Available: {available}")
    return strategies[key]
