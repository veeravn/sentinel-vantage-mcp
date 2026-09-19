"""Starter universe seed.

A liquid large-cap subset spanning sectors, plus SPY as the relative-strength
benchmark. This bootstraps development; the full S&P 500 / Russell 1000 membership and
its daily reconciliation come from an index/reference provider in a later step. Each
entry is point-in-time reference data written to the ``security`` table.
"""

from __future__ import annotations

from typing import TypedDict


class SeedSecurity(TypedDict, total=False):
    symbol: str
    name: str
    sector: str
    is_etf: bool
    is_benchmark: bool


BENCHMARK: SeedSecurity = {
    "symbol": "SPY",
    "name": "SPDR S&P 500 ETF Trust",
    "sector": "Index",
    "is_etf": True,
    "is_benchmark": True,
}

SEED_SECURITIES: list[SeedSecurity] = [
    BENCHMARK,
    {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "sector": "Technology"},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "sector": "Technology"},
    {"symbol": "AVGO", "name": "Broadcom Inc.", "sector": "Technology"},
    {"symbol": "AMD", "name": "Advanced Micro Devices", "sector": "Technology"},
    {"symbol": "ORCL", "name": "Oracle Corp.", "sector": "Technology"},
    {"symbol": "CRM", "name": "Salesforce Inc.", "sector": "Technology"},
    {"symbol": "GOOGL", "name": "Alphabet Inc. Class A", "sector": "Communication Services"},
    {"symbol": "META", "name": "Meta Platforms Inc.", "sector": "Communication Services"},
    {"symbol": "NFLX", "name": "Netflix Inc.", "sector": "Communication Services"},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Discretionary"},
    {"symbol": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Discretionary"},
    {"symbol": "HD", "name": "Home Depot Inc.", "sector": "Consumer Discretionary"},
    {"symbol": "MCD", "name": "McDonald's Corp.", "sector": "Consumer Discretionary"},
    {"symbol": "COST", "name": "Costco Wholesale Corp.", "sector": "Consumer Staples"},
    {"symbol": "PG", "name": "Procter & Gamble Co.", "sector": "Consumer Staples"},
    {"symbol": "KO", "name": "Coca-Cola Co.", "sector": "Consumer Staples"},
    {"symbol": "WMT", "name": "Walmart Inc.", "sector": "Consumer Staples"},
    {"symbol": "JPM", "name": "JPMorgan Chase & Co.", "sector": "Financials"},
    {"symbol": "BAC", "name": "Bank of America Corp.", "sector": "Financials"},
    {"symbol": "V", "name": "Visa Inc.", "sector": "Financials"},
    {"symbol": "MA", "name": "Mastercard Inc.", "sector": "Financials"},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway Class B", "sector": "Financials"},
    {"symbol": "UNH", "name": "UnitedHealth Group Inc.", "sector": "Health Care"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "Health Care"},
    {"symbol": "LLY", "name": "Eli Lilly and Co.", "sector": "Health Care"},
    {"symbol": "MRK", "name": "Merck & Co. Inc.", "sector": "Health Care"},
    {"symbol": "XOM", "name": "Exxon Mobil Corp.", "sector": "Energy"},
    {"symbol": "CVX", "name": "Chevron Corp.", "sector": "Energy"},
    {"symbol": "CAT", "name": "Caterpillar Inc.", "sector": "Industrials"},
    {"symbol": "GE", "name": "GE Aerospace", "sector": "Industrials"},
    {"symbol": "BA", "name": "Boeing Co.", "sector": "Industrials"},
    {"symbol": "LIN", "name": "Linde plc", "sector": "Materials"},
    {"symbol": "NEE", "name": "NextEra Energy Inc.", "sector": "Utilities"},
]
