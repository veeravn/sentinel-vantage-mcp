"""Feature engine correctness and missing-data handling."""

from __future__ import annotations

from datetime import timedelta

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
    assert fs.confidence < 1.0


def test_single_bar_yields_no_returns():
    bars = make_daily_bars("AAA", [50.0], [1_000_000.0])
    fs = compute_features("AAA", bars, as_of=as_of_of(bars))
    assert fs.return_1d is None
    assert fs.volume_ratio is None
    assert fs.completeness < 0.5


def _long(symbol, n=130):
    return make_daily_bars(symbol, [100.0 + i * 0.1 for i in range(n)])


def test_full_fresh_history_is_confident_and_shorter_history_lowers_it():
    long_bars, short_bars = _long("A", 130), _long("A", 70)
    bench = make_daily_bars("SPY", [100.0] * 130)
    full = compute_features("A", long_bars, as_of=as_of_of(long_bars), benchmark_bars=bench)
    short = compute_features("A", short_bars, as_of=as_of_of(short_bars), benchmark_bars=bench)
    assert full.confidence == 1.0
    assert short.confidence < full.confidence


def test_stale_latest_bar_lowers_confidence():
    bars = _long("A", 130)
    bench = make_daily_bars("SPY", [100.0] * 130)
    fresh = compute_features("A", bars, as_of=as_of_of(bars), benchmark_bars=bench)
    stale = compute_features(
        "A", bars, as_of=as_of_of(bars) + timedelta(days=8), benchmark_bars=bench
    )
    assert stale.confidence < fresh.confidence
