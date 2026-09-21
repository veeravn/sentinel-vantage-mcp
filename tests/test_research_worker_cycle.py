"""Research worker cycle: persists strategy scores and publishes per-strategy ranks, and
find_research_candidates serves the warm cache."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from conftest import make_daily_bars

from sentinel_vantage.apps.market_worker.research_scoring import run_research_cycle
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.briefing import BriefingService
from sentinel_vantage.domain.alerts.watchlist import WatchlistService
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.domain.research.models import ResearchResult
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.providers.base import FundamentalFact
from sentinel_vantage.storage.memory import (
    InMemoryAlertEventRepository,
    InMemoryAlertRuleRepository,
    InMemoryBarRepository,
    InMemoryEventRepository,
    InMemoryFundamentalRepository,
    InMemoryResearchScoreRepository,
    InMemoryScoreRepository,
    InMemoryWatchlistRepository,
)


def _payload(result):
    assert not result.is_error
    return json.loads(result.content[0].text)


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


def _facts(cik, *, rev_prior, rev):
    return [
        _annual(cik, "Revenues", rev_prior, 2024),
        _annual(cik, "Revenues", rev, 2025),
        _annual(cik, "EarningsPerShareDiluted", 5.0, 2025, unit="USD/shares"),
        _annual(cik, "GrossProfit", rev * 0.5, 2025),
        _annual(cik, "OperatingIncomeLoss", rev * 0.25, 2025),
        _annual(cik, "NetIncomeLoss", 200.0, 2025),
        FundamentalFact(
            cik=cik,
            tag="StockholdersEquity",
            unit="USD",
            value=1000.0,
            period_end=date(2025, 12, 31),
            fy=2025,
            fp="FY",
            form="10-K",
            filed_at=date(2026, 2, 1),
        ),
    ]


def _research_service() -> ResearchService:
    bars = InMemoryBarRepository(
        {
            "SPY": make_daily_bars("SPY", [100.0] * 130, [50_000_000.0] * 130),
            "GARPY": make_daily_bars(
                "GARPY", [80.0 + i * 0.15 for i in range(130)], [1_000_000.0] * 130
            ),
            "PEER1": make_daily_bars(
                "PEER1", [100.0 + i * 0.05 for i in range(130)], [1_000_000.0] * 130
            ),
            "PEER2": make_daily_bars("PEER2", [100.0] * 130, [1_000_000.0] * 130),
        }
    )
    funds = InMemoryFundamentalRepository()
    for sym, cik in [("GARPY", "C1"), ("PEER1", "C3"), ("PEER2", "C4")]:
        funds.set_cik(sym, cik)
    funds.set_facts("C1", _facts("C1", rev_prior=1000.0, rev=1300.0))  # +30%
    funds.set_facts("C3", _facts("C3", rev_prior=1000.0, rev=1150.0))  # +15%
    funds.set_facts("C4", _facts("C4", rev_prior=1000.0, rev=1120.0))  # +12%
    return ResearchService(bars, funds, scores=InMemoryResearchScoreRepository())


class _RecordingCache:
    """Duck-typed stand-in for RedisResearchRankCache (no Redis needed)."""

    def __init__(self) -> None:
        self.published: dict[str, list] = {}

    async def publish(self, strategy, results) -> None:
        self.published[strategy] = list(results)

    async def top(self, strategy, limit=20):
        return self.published.get(strategy, [])[:limit]


async def test_cycle_persists_and_publishes():
    research = _research_service()
    cache = _RecordingCache()
    as_of = await research.bars.latest_bar_ts()

    out = await run_research_cycle(research, cache, strategies=["GARP"], as_of=as_of)

    assert "garp-v1" in out
    # Persisted, so get_research_history now returns snapshots for the strategy.
    hist = await research.history(
        "GARPY", strategy="GARP", start=datetime(2026, 1, 1, tzinfo=UTC), end=as_of
    )
    assert len(hist) == 1
    # Published under the canonical strategy id, including the eligible names.
    assert "garp-v1" in cache.published
    assert "GARPY" in {r.symbol for r in cache.published["garp-v1"]}


async def test_cycle_skips_unknown_strategy():
    research = _research_service()
    as_of = await research.bars.latest_bar_ts()
    out = await run_research_cycle(research, None, strategies=["NOPE", "GARP"], as_of=as_of)
    assert set(out) == {"garp-v1"}  # bad name skipped, good one still scored


def _resources_with_cache(cache) -> MCPResources:
    research = _research_service()
    bars = research.bars
    trend_scores = InMemoryScoreRepository()
    service = TrendService(bars, scores=trend_scores)
    events = InMemoryEventRepository()
    watchlists = InMemoryWatchlistRepository()
    return MCPResources(
        settings=Settings(),
        db=None,
        redis=None,
        service=service,
        research=research,
        catalysts=CatalystService(bars, events),
        watchlists=watchlists,
        alert_rules=InMemoryAlertRuleRepository(),
        alert_events=InMemoryAlertEventRepository(),
        watchlist_service=WatchlistService(watchlists, service, trend_scores, events),
        briefing=BriefingService(service, research=research, alert_events=None),
        rank_cache=None,
        research_rank_cache=cache,
    )


async def test_find_research_candidates_serves_warm_cache():
    cache = _RecordingCache()
    cache.published["garp-v1"] = [
        ResearchResult(
            symbol="GARPY",
            strategy="garp-v1",
            as_of=datetime(2026, 4, 1, tzinfo=UTC),
            score=88.0,
            confidence=0.95,
            model_version="research-v1.0.0",
        )
    ]
    server = build_server(Settings(), resources=_resources_with_cache(cache))
    data = _payload(await server.call_tool("find_research_candidates", {"strategy": "GARP"}))[
        "data"
    ]
    assert data["source"] == "cache"
    assert [r["symbol"] for r in data["results"]] == ["GARPY"]


async def test_find_research_candidates_recomputes_on_cold_cache():
    server = build_server(Settings(), resources=_resources_with_cache(_RecordingCache()))
    data = _payload(await server.call_tool("find_research_candidates", {"strategy": "GARP"}))[
        "data"
    ]
    assert data["source"] == "compute"
    assert "GARPY" in {r["symbol"] for r in data["results"]}
