"""XBRL concept-tag normalization: each logical metric maps to a priority-ordered list
of candidate us-gaap/dei tags; the first with data for a period wins."""

from __future__ import annotations

REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
]
# Used to derive gross profit when GrossProfit is not reported.
COST_OF_REVENUE = [
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "CostOfGoodsSold",
    "CostOfServices",
]
NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]
EPS_DILUTED = [
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
]
GROSS_PROFIT = ["GrossProfit"]
OPERATING_INCOME = ["OperatingIncomeLoss"]
ASSETS = ["Assets"]
EQUITY = [
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]
LONG_TERM_DEBT = [
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
]
CASH = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
# us-gaap count is often absent; the dei cover-page concept backs it up (adapter scans both).
SHARES_OUTSTANDING = [
    "CommonStockSharesOutstanding",
    "EntityCommonStockSharesOutstanding",
]
OPERATING_CASH_FLOW = ["NetCashProvidedByUsedInOperatingActivities"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment"]

# Every tag we ingest per company (one companyfacts fetch covers all).
ALL_TAGS: list[str] = sorted(
    {
        *REVENUE,
        *COST_OF_REVENUE,
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
