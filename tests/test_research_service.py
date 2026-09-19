"""ResearchService end-to-end over in-memory bar + fundamental repositories."""

from __future__ import annotations

from datetime import date

from conftest import make_daily_bars

from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.providers.base import FundamentalFact
from sentinel_vantage.storage.memory import (
    InMemoryBarRepository,
    InMemoryFundamentalRepository,
    InMemoryResearchScoreRepository,
)


def _annual(cik, tag, value, year, unit="USD"):
    return FundamentalFact(
        cik=cik,
        tag=tag,
        unit=unit,
        value=value,
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        fy=year,
        fp="FY",
        form="10-K",
        filed_at=date(year + 1, 2, 1),
    )


def _facts(cik, *, rev_prior, rev, eps=5.0, gp_ratio=0.5, ni=200.0, equity=1000.0):
    return [
        _annual(cik, "Revenues", rev_prior, 2024),
        _annual(cik, "Revenues", rev, 2025),
        _annual(cik, "EarningsPerShareDiluted", eps, 2025, unit="USD/shares"),
        _annual(cik, "GrossProfit", rev * gp_ratio, 2025),
        _annual(cik, "OperatingIncomeLoss", rev * 0.25, 2025),
        _annual(cik, "NetIncomeLoss", ni, 2025),
        FundamentalFact(
            cik=cik,
            tag="StockholdersEquity",
            unit="USD",
            value=equity,
            period_end=date(2025, 12, 31),
            fy=2025,
            fp="FY",
            form="10-K",
            filed_at=date(2026, 2, 1),
        ),
    ]


def _setup():
    # Rising price for growth names, flat for peers; all liquid and > $3.
    bars = InMemoryBarRepository(
        {
            "SPY": make_daily_bars("SPY", [100.0] * 130, [50_000_000.0] * 130),
            "GARPY": make_daily_bars(
                "GARPY", [80.0 + i * 0.15 for i in range(130)], [1_000_000.0] * 130
            ),
            "SLOW": make_daily_bars("SLOW", [100.0] * 130, [1_000_000.0] * 130),
            "PEER1": make_daily_bars(
                "PEER1", [100.0 + i * 0.05 for i in range(130)], [1_000_000.0] * 130
            ),
            "PEER2": make_daily_bars("PEER2", [100.0] * 130, [1_000_000.0] * 130),
            "NOCIK": make_daily_bars("NOCIK", [100.0] * 130, [1_000_000.0] * 130),
        }
    )
    funds = InMemoryFundamentalRepository()
    for sym, cik in [("GARPY", "C1"), ("SLOW", "C2"), ("PEER1", "C3"), ("PEER2", "C4")]:
        funds.set_cik(sym, cik)
    # NOCIK deliberately has no CIK mapping.
    funds.set_facts("C1", _facts("C1", rev_prior=1000.0, rev=1300.0))  # +30% growth
    funds.set_facts(
        "C2", _facts("C2", rev_prior=1000.0, rev=1030.0, eps=3.0, ni=80.0)
    )  # +3% -> gate
    funds.set_facts("C3", _facts("C3", rev_prior=1000.0, rev=1150.0))  # +15%
    funds.set_facts("C4", _facts("C4", rev_prior=1000.0, rev=1120.0))  # +12%
    return bars, funds


def _as_of(bars):
    return bars._histories["GARPY"][-1].ts


async def test_rank_applies_gates_and_scores():
    bars, funds = _setup()
    svc = ResearchService(bars, funds)
    rank = await svc.rank("GARP", as_of=_as_of(bars), limit=10)

    ranked = [r.symbol for r in rank.results]
    assert "GARPY" in ranked
    # SLOW fails the revenue-growth hard gate; NOCIK has no fundamentals.
    fails = {e.symbol: e.hard_gate_failures for e in rank.ineligible}
    assert "GATE_GROWTH_BELOW_MIN" in fails.get("SLOW", [])
    assert "GATE_NO_FUNDAMENTALS" in fails.get("NOCIK", [])
    assert "SLOW" not in ranked


async def test_compare_scores_given_symbols():
    bars, funds = _setup()
    svc = ResearchService(bars, funds)
    cmp = await svc.compare(["GARPY", "PEER1", "PEER2"], strategy="GARP", as_of=_as_of(bars))
    assert {r.symbol for r in cmp.results} == {"GARPY", "PEER1", "PEER2"}


async def test_persist_and_history_roundtrip():
    bars, funds = _setup()
    scores = InMemoryResearchScoreRepository()
    svc = ResearchService(bars, funds, scores=scores)
    as_of = _as_of(bars)
    await svc.rank("GARP", as_of=as_of, persist=True)
    hist = await svc.history("GARPY", strategy="GARP", start=as_of.replace(hour=0), end=as_of)
    assert len(hist) == 1 and hist[0].symbol == "GARPY"
