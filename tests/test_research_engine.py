"""research-v1 scoring: ranking, penalties, reasons, determinism."""

from __future__ import annotations

from datetime import UTC, datetime

from sentinel_vantage.domain.research.engine import ResearchInputs, score_research
from sentinel_vantage.domain.research.models import Fundamentals
from sentinel_vantage.domain.research.strategy import get_strategy

AS_OF = datetime(2026, 6, 1, tzinfo=UTC)


def _inputs(symbol, **kw):
    fund = Fundamentals(
        symbol=symbol,
        cik="C",
        as_of=AS_OF,
        revenue_growth_yoy=kw.get("growth"),
        eps_growth_yoy=kw.get("eps_growth"),
        gross_margin=kw.get("gm"),
        operating_margin=kw.get("om"),
        roe=kw.get("roe"),
        debt_to_equity=kw.get("dte"),
        pe=kw.get("pe"),
        ev_to_sales=kw.get("evs"),
        data_confidence=1.0,
    )
    return ResearchInputs(
        fundamentals=fund,
        momentum_6m=kw.get("mom"),
        realized_vol_20d=kw.get("vol"),
        return_1d=kw.get("ret1d"),
    )


def _universe():
    u = {
        # High growth, high quality, reasonably priced, strong momentum -> should win.
        "GARPY": _inputs(
            "GARPY",
            growth=0.30,
            eps_growth=0.35,
            gm=0.6,
            om=0.3,
            roe=0.25,
            dte=0.3,
            pe=22,
            evs=6,
            mom=0.30,
        ),
        # Cheap but slow and low quality.
        "SLOW": _inputs(
            "SLOW",
            growth=0.09,
            eps_growth=0.05,
            gm=0.2,
            om=0.08,
            roe=0.05,
            dte=0.6,
            pe=8,
            evs=1.5,
            mom=-0.10,
        ),
        # Growthy but heavily levered and volatile -> penalties bite.
        "RISKY": _inputs(
            "RISKY",
            growth=0.28,
            eps_growth=0.30,
            gm=0.55,
            om=0.25,
            roe=0.22,
            dte=3.0,
            pe=25,
            evs=7,
            mom=0.25,
            vol=0.08,
            ret1d=0.20,
        ),
    }
    for i in range(8):  # fillers near the mean for stable z-scores
        u[f"N{i:02d}"] = _inputs(
            f"N{i:02d}",
            growth=0.15,
            eps_growth=0.15,
            gm=0.35,
            om=0.15,
            roe=0.12,
            dte=0.8,
            pe=15,
            evs=3,
            mom=0.05,
        )
    return u


def test_garp_ranks_growth_at_reasonable_price_on_top():
    results = score_research(_universe(), profile=get_strategy("GARP"), as_of=AS_OF)
    assert results[0].symbol == "GARPY"
    top = results[0]
    assert top.model_version == "research-v1.0.0"
    assert top.strategy == "garp-v1"
    assert "STRONG_GROWTH" in top.positive_reasons
    assert top.rank_percentile == 100.0


def test_leverage_and_volatility_penalties_apply():
    results = {
        r.symbol: r for r in score_research(_universe(), profile=get_strategy("GARP"), as_of=AS_OF)
    }
    risky = results["RISKY"]
    assert "leverage" in risky.penalties
    assert "extreme_volatility" in risky.penalties
    assert "extreme_short_term_move" in risky.penalties
    assert "HIGH_LEVERAGE" in risky.negative_reasons


def test_scoring_is_deterministic():
    u = _universe()
    a = [
        r.model_dump(mode="json")
        for r in score_research(u, profile=get_strategy("GARP"), as_of=AS_OF)
    ]
    b = [
        r.model_dump(mode="json")
        for r in score_research(u, profile=get_strategy("GARP"), as_of=AS_OF)
    ]
    assert a == b


def test_empty_universe():
    assert score_research({}, profile=get_strategy("GARP"), as_of=AS_OF) == []
