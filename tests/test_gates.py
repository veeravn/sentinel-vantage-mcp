"""Eligibility gates: a failing symbol is ineligible, never a normal-confidence zero."""

from __future__ import annotations

from conftest import as_of_of, make_daily_bars

from sentinel_vantage.domain.features.engine import compute_features
from sentinel_vantage.domain.trend.gates import (
    GATE_HISTORY,
    GATE_LIQUIDITY,
    GATE_MISSING_DATA,
    GATE_PRICE,
    evaluate_gates,
)


def _features(symbol, closes, volumes=None):
    bars = make_daily_bars(symbol, closes, volumes)
    bench = make_daily_bars("SPY", [100.0] * len(closes))
    return compute_features(symbol, bars, as_of=as_of_of(bars), benchmark_bars=bench)


def test_liquid_large_cap_passes():
    fs = _features("AAA", [100.0] * 70, [2_000_000.0] * 70)  # $200M/day
    elig = evaluate_gates(fs)
    assert elig.eligible
    assert elig.gate_failures == []


def test_penny_stock_fails_price_gate():
    fs = _features("PENNY", [1.5] * 70, [20_000_000.0] * 70)
    elig = evaluate_gates(fs)
    assert not elig.eligible
    assert GATE_PRICE in elig.gate_failures


def test_illiquid_fails_liquidity_gate():
    fs = _features("THIN", [100.0] * 70, [1_000.0] * 70)  # $100k/day
    elig = evaluate_gates(fs)
    assert GATE_LIQUIDITY in elig.gate_failures


def test_short_history_fails_history_gate():
    fs = _features("NEW", [100.0] * 30, [2_000_000.0] * 30)
    elig = evaluate_gates(fs)
    assert GATE_HISTORY in elig.gate_failures


def test_inactive_listing_is_ineligible():
    fs = _features("DEAD", [100.0] * 70, [2_000_000.0] * 70)
    elig = evaluate_gates(fs, is_active=False)
    assert not elig.eligible


def test_missing_recent_data_gate():
    # AT-2: a single-bar symbol cannot produce a 1d return -> missing-data gate.
    bars = make_daily_bars("AAA", [100.0], [2_000_000.0])
    fs = compute_features("AAA", bars, as_of=as_of_of(bars))
    elig = evaluate_gates(fs)
    assert GATE_MISSING_DATA in elig.gate_failures
