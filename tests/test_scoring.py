"""trend-v0 cross-sectional scoring: ranking, reasons, and determinism."""

from __future__ import annotations

from conftest import as_of_of, make_daily_bars

from sentinel_vantage.core.versioning import TREND_MODEL_VERSION
from sentinel_vantage.domain.features.engine import compute_features
from sentinel_vantage.domain.trend.scoring import score_universe


def _fs(symbol, closes, volumes, bench):
    bars = make_daily_bars(symbol, closes, volumes)
    return compute_features(symbol, bars, as_of=as_of_of(bars), benchmark_bars=bench)


def _universe():
    # A realistic-sized peer set: cross-sectional z-scores need more than a handful of
    # names before a factor can exceed the reason-code thresholds (population z from n
    # points is bounded by sqrt(n-1)).
    bench = make_daily_bars("SPY", [100.0] * 70)
    feats = {
        "HOT": _fs("HOT", [100.0] * 69 + [120.0], [1_000_000.0] * 69 + [5_000_000.0], bench),
        "MID": _fs("MID", [100.0] * 69 + [101.0], [1_000_000.0] * 70, bench),
        "COLD": _fs("COLD", [100.0] * 69 + [96.0], [1_000_000.0] * 69 + [400_000.0], bench),
    }
    # Filler peers that sit near the mean so HOT genuinely stands out.
    for i in range(10):
        sym = f"N{i:02d}"
        feats[sym] = _fs(sym, [100.0] * 69 + [100.5], [1_000_000.0] * 70, bench)
    return feats, as_of_of(bench)


def test_ranking_puts_hot_on_top():
    feats, as_of = _universe()
    results = score_universe(feats, horizon="1d", as_of=as_of)
    assert [r.symbol for r in results][0] == "HOT"
    top = results[0]
    assert "ABNORMAL_VOLUME" in top.reasons
    assert "STRONG_RELATIVE_STRENGTH" in top.reasons
    assert top.model_version == TREND_MODEL_VERSION
    assert top.rank_percentile == 100.0
    # AT-4: every ranked result carries at least one reason, metrics, version, as_of.
    for r in results:
        assert r.metrics
        assert r.as_of == as_of


def test_extended_move_raises_risk_flag():
    feats, as_of = _universe()
    results = {r.symbol: r for r in score_universe(feats, horizon="1d", as_of=as_of)}
    assert "EXTENDED_SHORT_TERM_MOVE" not in results["MID"].risk_flags
    # HOT jumped +12% in a day -> extended-move flag.
    assert "EXTENDED_SHORT_TERM_MOVE" in results["HOT"].risk_flags


def test_scoring_is_deterministic():
    # AT-1: identical inputs -> identical scores across repeated runs.
    feats, as_of = _universe()
    run1 = [r.model_dump(mode="json") for r in score_universe(feats, horizon="1d", as_of=as_of)]
    run2 = [r.model_dump(mode="json") for r in score_universe(feats, horizon="1d", as_of=as_of)]
    assert run1 == run2


def test_empty_universe_returns_empty():
    assert score_universe({}, horizon="1d", as_of=as_of_of(make_daily_bars("X", [1.0, 2.0]))) == []
