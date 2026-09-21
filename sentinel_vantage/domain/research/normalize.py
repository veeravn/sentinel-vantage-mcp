"""Normalize point-in-time XBRL facts (+ price) into comparable metrics. Pure and
deterministic: income-statement flows use the latest-filed full-year value per period;
balance-sheet stocks use the most recent instant."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

from sentinel_vantage.domain.research import tags as T
from sentinel_vantage.domain.research.models import Fundamentals
from sentinel_vantage.providers.base import FundamentalFact

# Metrics whose absence drives data_confidence / missing.
_KEY_METRICS = ("revenue", "revenue_growth_yoy", "eps", "gross_margin", "roe")


def _annual_by_period(
    facts: Sequence[FundamentalFact], candidate_tags: Sequence[str]
) -> dict[date, float]:
    """Full-year value keyed by fiscal period end, for the first candidate tag with data
    (latest-filed version of each period wins). The period map lets callers align a
    numerator to its own denominator year."""
    for tag in candidate_tags:
        by_period: dict[date, tuple[date, float]] = {}
        for f in facts:
            if f.tag != tag or f.fp != "FY":
                continue
            prev = by_period.get(f.period_end)
            if prev is None or f.filed_at > prev[0]:
                by_period[f.period_end] = (f.filed_at, f.value)
        if by_period:
            return {p: v for p, (_, v) in by_period.items()}
    return {}


def _annual_series(facts: Sequence[FundamentalFact], candidate_tags: Sequence[str]) -> list[float]:
    """Full-year values, oldest→newest, for the first candidate tag that has data."""
    by_period = _annual_by_period(facts, candidate_tags)
    return [by_period[p] for p in sorted(by_period)]


def _latest_instant(
    facts: Sequence[FundamentalFact], candidate_tags: Sequence[str]
) -> float | None:
    """Most recent balance-sheet value for the first candidate tag with data."""
    for tag in candidate_tags:
        best: tuple[date, date, float] | None = None
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
    rev_by_period = _annual_by_period(facts, T.REVENUE)
    rev_periods = sorted(rev_by_period)
    latest = rev_periods[-1] if rev_periods else None

    revenue = rev_by_period[latest] if latest is not None else None
    revenue_prior = rev_by_period[rev_periods[-2]] if len(rev_periods) >= 2 else None

    eps_series = _annual_series(facts, T.EPS_DILUTED)
    eps = eps_series[-1] if eps_series else None
    eps_prior = eps_series[-2] if len(eps_series) >= 2 else None

    # Align margin/return numerators to the latest revenue year, else their own latest.
    def _aligned(by_period: dict[date, float]) -> float | None:
        if latest is not None and latest in by_period:
            return by_period[latest]
        return by_period[max(by_period)] if by_period else None

    gross_by_period = _annual_by_period(facts, T.GROSS_PROFIT)
    op_by_period = _annual_by_period(facts, T.OPERATING_INCOME)
    ni_by_period = _annual_by_period(facts, T.NET_INCOME)

    net_income = _aligned(ni_by_period)
    operating_income = _aligned(op_by_period)
    gross_profit = _aligned(gross_by_period)
    # Derive gross profit from revenue - cost of revenue for the same year when untagged.
    if gross_profit is None and revenue is not None and latest is not None:
        cogs_by_period = _annual_by_period(facts, T.COST_OF_REVENUE)
        cogs = cogs_by_period.get(latest)
        if cogs is not None:
            gross_profit = revenue - cogs

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
