"""Fundamentals normalization: growth, margins, valuation, tag priority, point-in-time."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sentinel_vantage.domain.research.normalize import compute_fundamentals
from sentinel_vantage.providers.base import FundamentalFact


def _annual(tag, value, year, *, filed_month=2, unit="USD"):
    return FundamentalFact(
        cik="C",
        tag=tag,
        unit=unit,
        value=value,
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        fy=year,
        fp="FY",
        form="10-K",
        filed_at=date(year + 1, filed_month, 1),
    )


def _instant(tag, value, year, *, unit="USD"):
    return FundamentalFact(
        cik="C",
        tag=tag,
        unit=unit,
        value=value,
        period_end=date(year, 12, 31),
        fy=year,
        fp="FY",
        form="10-K",
        filed_at=date(year + 1, 2, 1),
    )


def _facts():
    return [
        _annual("Revenues", 1000.0, 2022),
        _annual("Revenues", 1200.0, 2023),  # +20% YoY
        _annual("EarningsPerShareDiluted", 4.0, 2022, unit="USD/shares"),
        _annual("EarningsPerShareDiluted", 5.0, 2023, unit="USD/shares"),  # +25%
        _annual("GrossProfit", 600.0, 2023),  # 50% gross margin
        _annual("OperatingIncomeLoss", 300.0, 2023),  # 25% op margin
        _annual("NetIncomeLoss", 240.0, 2023),
        _instant("StockholdersEquity", 1200.0, 2023),  # ROE = 240/1200 = 20%
        _instant("LongTermDebt", 600.0, 2023),  # D/E = 0.5
        _instant("CashAndCashEquivalentsAtCarryingValue", 200.0, 2023),
        _instant("CommonStockSharesOutstanding", 100.0, 2023, unit="shares"),
    ]


def test_core_metrics():
    f = compute_fundamentals(
        "ABC", "C", _facts(), price=50.0, as_of=datetime(2024, 6, 1, tzinfo=UTC)
    )
    assert round(f.revenue_growth_yoy, 4) == 0.2
    assert round(f.eps_growth_yoy, 4) == 0.25
    assert round(f.gross_margin, 4) == 0.5
    assert round(f.operating_margin, 4) == 0.25
    assert round(f.roe, 4) == 0.2
    assert round(f.debt_to_equity, 4) == 0.5
    assert f.market_cap == 5000.0  # 50 * 100 shares
    assert round(f.pe, 4) == 10.0  # 50 / 5 eps
    # EV = 5000 + 600 - 200 = 5400; EV/Sales = 5400/1200
    assert round(f.ev_to_sales, 4) == round(5400 / 1200, 4)
    assert f.data_confidence == 1.0
    assert f.missing == []


def test_tag_priority_falls_back():
    # No RevenueFromContractWithCustomer... but Revenues present -> used.
    facts = [_annual("Revenues", 500.0, 2023), _annual("Revenues", 400.0, 2022)]
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert f.revenue == 500.0
    assert round(f.revenue_growth_yoy, 4) == 0.25


def test_missing_metrics_lower_confidence():
    facts = [_annual("Revenues", 500.0, 2023)]  # only one year, no eps/margins/roe
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert f.revenue_growth_yoy is None  # no prior year
    assert f.data_confidence < 1.0
    assert "eps" in f.missing


def test_restatement_latest_filed_wins():
    facts = [
        _annual("Revenues", 1000.0, 2023, filed_month=2),
        _annual("Revenues", 1050.0, 2023, filed_month=8),  # restatement, later filed
    ]
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2025, 1, 1, tzinfo=UTC))
    assert f.revenue == 1050.0  # latest-filed version of the period


def test_gross_margin_derived_from_cost_of_revenue():
    # No GrossProfit tag, but revenue and cost of revenue for the same year -> derived.
    facts = [
        _annual("Revenues", 1000.0, 2022),
        _annual("Revenues", 1200.0, 2023),
        _annual("CostOfRevenue", 700.0, 2023),  # gross profit = 1200 - 700 = 500
    ]
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert round(f.gross_margin, 4) == round(500 / 1200, 4)
    assert "gross_margin" not in f.missing


def test_gross_profit_not_derived_across_mismatched_years():
    # Cost of revenue only for a non-latest year must not pair with latest revenue.
    facts = [
        _annual("Revenues", 1000.0, 2022),
        _annual("Revenues", 1200.0, 2023),
        _annual("CostOfRevenue", 700.0, 2022),  # wrong year — not the latest revenue
    ]
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert f.gross_margin is None


def test_shares_dei_fallback_feeds_market_cap():
    # us-gaap CommonStockSharesOutstanding absent; dei cover-page concept present.
    facts = [
        _annual("Revenues", 1200.0, 2023),
        _instant("EntityCommonStockSharesOutstanding", 100.0, 2023, unit="shares"),
    ]
    f = compute_fundamentals("ABC", "C", facts, price=50.0, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert f.shares_outstanding == 100.0
    assert f.market_cap == 5000.0


def test_alternate_revenue_tag_priority():
    # ASC 606 concept used instead of Revenues -> resolved via priority list.
    facts = [
        _annual("RevenueFromContractWithCustomerExcludingAssessedTax", 400.0, 2022),
        _annual("RevenueFromContractWithCustomerExcludingAssessedTax", 500.0, 2023),
    ]
    f = compute_fundamentals("ABC", "C", facts, price=None, as_of=datetime(2024, 6, 1, tzinfo=UTC))
    assert f.revenue == 500.0
    assert round(f.revenue_growth_yoy, 4) == 0.25
