"""Feature engine correctness and missing-data handling."""

from __future__ import annotations

from conftest import as_of_of, make_daily_bars

from sentinel_vantage.domain.features.engine import compute_features


def test_basic_returns_and_volume_ratio():
    # 10 flat days at 100, then a jump to 110 on 3x volume.
    closes = [100.0] * 9 + [110.0]
    volumes = [1_000_000.0] * 9 + [3_000_000.0]
    bars = make_daily_bars("AAA", closes, volumes)
    bench = make_daily_bars("SPY", [100.0] * 10)

    fs = compute_features("AAA", bars, as_of=as_of_of(bars), benchmark_bars=bench)

    assert fs.n_days == 10
    assert fs.last_price == 110.0
    assert round(fs.return_1d, 4) == 0.1  # 100 -> 110
    assert fs.volume_ratio == 3.0  # 3M vs 1M median baseline
    # SPY flat, so AAA's +10% is all relative strength.
    assert round(fs.relative_strength_1d, 4) == 0.1
    assert fs.benchmark_available is True


def test_missing_benchmark_lowers_confidence_and_rs():
    bars = make_daily_bars("AAA", [100.0] * 9 + [105.0])
    fs = compute_features("AAA", bars, as_of=as_of_of(bars), benchmark_bars=None)
    assert fs.relative_strength_1d is None
    assert fs.benchmark_available is False
    # completeness 4/5 * history 0.8 * benchmark 0.7
    assert fs.confidence < 1.0


def test_single_bar_yields_no_returns():
    bars = make_daily_bars("AAA", [50.0], [1_000_000.0])
    fs = compute_features("AAA", bars, as_of=as_of_of(bars))
    assert fs.return_1d is None
    assert fs.volume_ratio is None
    assert fs.completeness < 0.5
