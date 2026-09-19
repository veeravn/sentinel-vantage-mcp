"""Normalize point-in-time XBRL facts (+ price) into comparable metrics.

Pure and deterministic. Two selection modes:

- **annual series** (income-statement flows: revenue, net income, EPS, margins): the
  full-year (fp == "FY") value per fiscal period, taking the latest-filed version of
  each period (so a restatement visible as-of wins). Growth compares the two most
  recent annual periods.
- **latest instant** (balance-sheet stocks: equity, debt, cash, shares): the value with
  the most recent period end, latest-filed on ties.

Tag priority (domain.research.tags) handles issuers that report the same quantity under
different concepts: the first candidate tag with data wins.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sentinel_vantage.domain.research import tags as T
from sentinel_vantage.domain.research.models import Fundamentals
from sentinel_vantage.providers.base import FundamentalFact

# Metrics whose absence most undermines a research score (drives data_confidence/missing).
_KEY_METRICS = ("revenue", "revenue_growth_yoy", "eps", "gross_margin", "roe")


def _annual_series(facts: Sequence[FundamentalFact], candidate_tags: Sequence[str]) -> list[float]:
    """Full-year values, oldest→newest, for the first candidate tag that has data."""
    for tag in candidate_tags:
        by_period: dict[date, tuple[date, float]] = {}
        for f in facts:
            if f.tag != tag or f.fp != "FY":
                continue
            prev = by_period.get(f.period_end)
            if prev is None or f.filed_at > prev[0]:
                by_period[f.period_end] = (f.filed_at, f.value)
        if by_period:
            return [v for _, v in (by_period[p] for p in sorted(by_period))]
    return []


def _latest_instant(
    facts: Sequence[FundamentalFact], candidate_tags: Sequence[str]
) -> float | None:
    """Most recent balance-sheet value for the first candidate tag with data."""
    for tag in candidate_tags:
        best: tuple[date, date, float] | None = None  # (period_end, filed_at, value)
        for f in facts:
            if f.tag != tag:
                continue
            key = (f.period_end, f.filed_at, f.value)
            if best is None or (f.period_end, f.filed_at) > (best[0], best[1]):
                best = key
        if best is not None:
            return best[2]
    return None


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior == 0:
        return None
    return current / prior - 1.0


def _ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def compute_fundamentals(
    symbol: str,
    cik: str,
    facts: Sequence[FundamentalFact],
    *,
    price: float | None,
    as_of: datetime,
) -> Fundamentals:
    revenue_series = _annual_series(facts, T.REVENUE)
    eps_series = _annual_series(facts, T.EPS_DILUTED)
    gross_series = _annual_series(facts, T.GROSS_PROFIT)
    op_series = _annual_series(facts, T.OPERATING_INCOME)
    ni_series = _annual_series(facts, T.NET_INCOME)

    revenue = revenue_series[-1] if revenue_series else None
    revenue_prior = revenue_series[-2] if len(revenue_series) >= 2 else None
    eps = eps_series[-1] if eps_series else None
    eps_prior = eps_series[-2] if len(eps_series) >= 2 else None
    net_income = ni_series[-1] if ni_series else None
    gross_profit = gross_series[-1] if gross_series else None
    operating_income = op_series[-1] if op_series else None

    equity = _latest_instant(facts, T.EQUITY)
    debt = _latest_instant(facts, T.LONG_TERM_DEBT)
    cash = _latest_instant(facts, T.CASH)
    shares = _latest_instant(facts, T.SHARES_OUTSTANDING)

    market_cap = price * shares if (price is not None and shares) else None
    net_debt = (debt or 0.0) - (cash or 0.0) if (debt is not None or cash is not None) else None
    ev = market_cap + (debt or 0.0) - (cash or 0.0) if market_cap is not None else None

    f = Fundamentals(
        symbol=symbol,
        cik=cik,
        as_of=as_of,
        revenue=revenue,
        revenue_prior=revenue_prior,
        revenue_growth_yoy=_growth(revenue, revenue_prior),
        eps=eps,
        eps_prior=eps_prior,
        eps_growth_yoy=_growth(eps, eps_prior),
        gross_margin=_ratio(gross_profit, revenue),
        operating_margin=_ratio(operating_income, revenue),
        roe=_ratio(net_income, equity),
        debt_to_equity=_ratio(debt, equity),
        net_debt=net_debt,
        price=price,
        shares_outstanding=shares,
        market_cap=market_cap,
        pe=(price / eps if (price is not None and eps and eps > 0) else None),
        ev_to_sales=_ratio(ev, revenue),
    )

    missing = [m for m in _KEY_METRICS if getattr(f, m) is None]
    f.missing = missing
    f.data_confidence = round(1.0 - len(missing) / len(_KEY_METRICS), 4)
    return f
