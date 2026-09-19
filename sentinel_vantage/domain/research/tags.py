"""XBRL concept-tag normalization.

Issuers report the same economic quantity under different us-gaap tags, so each logical
metric maps to a priority-ordered list of candidate tags. The normalization layer picks
the first tag that has data for a period. This is the crux of cross-company
comparability the design calls out (section 8.2).
"""

from __future__ import annotations

# Priority-ordered candidate tags per logical metric (first with data wins).
REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
NET_INCOME = ["NetIncomeLoss"]
EPS_DILUTED = ["EarningsPerShareDiluted"]
GROSS_PROFIT = ["GrossProfit"]
OPERATING_INCOME = ["OperatingIncomeLoss"]
ASSETS = ["Assets"]
EQUITY = ["StockholdersEquity"]
LONG_TERM_DEBT = ["LongTermDebtNoncurrent", "LongTermDebt"]
CASH = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
SHARES_OUTSTANDING = ["CommonStockSharesOutstanding"]
OPERATING_CASH_FLOW = ["NetCashProvidedByUsedInOperatingActivities"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment"]

# Every tag we ingest for a company (single companyfacts fetch covers all).
ALL_TAGS: list[str] = sorted(
    {
        *REVENUE,
        *NET_INCOME,
        *EPS_DILUTED,
        *GROSS_PROFIT,
        *OPERATING_INCOME,
        *ASSETS,
        *EQUITY,
        *LONG_TERM_DEBT,
        *CASH,
        *SHARES_OUTSTANDING,
        *OPERATING_CASH_FLOW,
        *CAPEX,
    }
)
