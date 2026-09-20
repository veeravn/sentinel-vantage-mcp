"""XBRL concept-tag normalization.

Issuers report the same economic quantity under different us-gaap tags, so each logical
metric maps to a priority-ordered list of candidate tags. The normalization layer picks
the first tag that has data for a period. This is the crux of cross-company
comparability the design calls out (section 8.2).
"""

from __future__ import annotations

# Priority-ordered candidate tags per logical metric (first with data wins). Lists are
# ordered most-standard first; alternates cover issuers that tag the same economic
# quantity under a different concept (ASC 606 revenue variants, combined basic/diluted
# EPS, NCI-inclusive equity, capital-lease-inclusive debt).
REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
]
# Cost of revenue — used to derive gross profit when GrossProfit is not reported.
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
# CommonStockSharesOutstanding (us-gaap) is often absent; the dei cover-page concept
# EntityCommonStockSharesOutstanding is almost always present. The SEC adapter scans
# both taxonomies, so listing the dei tag here is enough for it to be ingested.
SHARES_OUTSTANDING = [
    "CommonStockSharesOutstanding",
    "EntityCommonStockSharesOutstanding",
]
OPERATING_CASH_FLOW = ["NetCashProvidedByUsedInOperatingActivities"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment"]

# Every tag we ingest for a company (single companyfacts fetch covers all).
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
