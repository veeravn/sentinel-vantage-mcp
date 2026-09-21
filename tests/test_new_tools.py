"""Tier 1 read tools and Tier 3 lifecycle tools over in-memory resources."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.briefing import BriefingService
from sentinel_vantage.domain.alerts.watchlist import WatchlistService
from sentinel_vantage.domain.catalysts.models import Event
from sentinel_vantage.domain.catalysts.service import CatalystService
from sentinel_vantage.domain.research.models import ResearchResult
from sentinel_vantage.domain.research.service import ResearchService
from sentinel_vantage.domain.trend.service import TrendService
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


def _resources() -> MCPResources:
    histories = {
        "SPY": make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70),
        "NVDA": make_daily_bars("NVDA", [100.0] * 69 + [108.0], [1_000_000.0] * 69 + [4_000_000.0]),
    }
    bars = InMemoryBarRepository(histories)
    trend_scores = InMemoryScoreRepository()
    service = TrendService(bars, scores=trend_scores)
    research = ResearchService(
        bars, InMemoryFundamentalRepository(), scores=InMemoryResearchScoreRepository()
    )
    events = InMemoryEventRepository()
    catalysts = CatalystService(bars, events)
    watchlists = InMemoryWatchlistRepository()
    alert_rules = InMemoryAlertRuleRepository()
    alert_events = InMemoryAlertEventRepository()
    return MCPResources(
        settings=Settings(),
        db=None,
        redis=None,
        service=service,
        research=research,
        catalysts=catalysts,
        watchlists=watchlists,
        alert_rules=alert_rules,
        alert_events=alert_events,
        watchlist_service=WatchlistService(watchlists, service, trend_scores, events),
        briefing=BriefingService(service, research=research, alert_events=alert_events),
        rank_cache=None,
    )


async def test_new_tools_registered():
    server = build_server(Settings(), resources=_resources())
    names = {t.name for t in await server.list_tools()}
    assert {
        "list_strategies",
        "get_research_history",
        "get_recent_filings",
        "list_alert_rules",
        "get_watchlist",
        "update_watchlist",
        "delete_watchlist",
        "disable_alert_rule",
        "delete_alert_rule",
    } <= names


async def test_list_strategies_exposes_packaged_profiles():
    server = build_server(Settings(), resources=_resources())
    data = _payload(await server.call_tool("list_strategies", {}))["data"]
    ids = {s["id"] for s in data["strategies"]}
    assert {"garp-v1", "growth-v1", "quality-v1", "value-v1", "momentum-v1"} <= ids
    garp = next(s for s in data["strategies"] if s["id"] == "garp-v1")
    assert garp["weights"] and "score_version" in garp


async def test_watchlist_get_update_delete_lifecycle():
    server = build_server(Settings(), resources=_resources())
    created = _payload(
        await server.call_tool("create_watchlist", {"name": "mine", "symbols": ["nvda", "aapl"]})
    )
    wl_id = created["data"]["watchlist_id"]

    got = _payload(await server.call_tool("get_watchlist", {"watchlist_id": wl_id}))["data"]
    assert got["found"] is True
    assert got["watchlist"]["symbols"] == ["NVDA", "AAPL"]

    updated = _payload(
        await server.call_tool(
            "update_watchlist", {"watchlist_id": wl_id, "add": ["msft"], "remove": ["aapl"]}
        )
    )["data"]
    assert updated["watchlist"]["symbols"] == ["NVDA", "MSFT"]

    deleted = _payload(await server.call_tool("delete_watchlist", {"watchlist_id": wl_id}))["data"]
    assert deleted["deleted"] is True
    gone = _payload(await server.call_tool("get_watchlist", {"watchlist_id": wl_id}))["data"]
    assert gone["found"] is False


async def test_update_and_delete_missing_watchlist():
    server = build_server(Settings(), resources=_resources())
    upd = _payload(await server.call_tool("update_watchlist", {"watchlist_id": "nope"}))["data"]
    assert upd["found"] is False
    dele = _payload(await server.call_tool("delete_watchlist", {"watchlist_id": "nope"}))["data"]
    assert dele["deleted"] is False


async def test_alert_rule_list_disable_delete_lifecycle():
    server = build_server(Settings(), resources=_resources())
    created = _payload(
        await server.call_tool(
            "create_alert_rule",
            {"all_conditions": ["trend_score >= 85"], "symbols": ["NVDA"]},
        )
    )
    rule_id = created["data"]["rule_id"]

    listed = _payload(await server.call_tool("list_alert_rules", {}))["data"]
    assert rule_id in {r["rule_id"] for r in listed["rules"]}

    disabled = _payload(await server.call_tool("disable_alert_rule", {"rule_id": rule_id}))["data"]
    assert disabled["found"] is True and disabled["active"] is False
    # Deactivated rules drop out of the active-rules listing.
    after = _payload(await server.call_tool("list_alert_rules", {}))["data"]
    assert rule_id not in {r["rule_id"] for r in after["rules"]}

    deleted = _payload(await server.call_tool("delete_alert_rule", {"rule_id": rule_id}))["data"]
    assert deleted["deleted"] is True


async def test_disable_missing_rule_reports_not_found():
    server = build_server(Settings(), resources=_resources())
    res = _payload(await server.call_tool("disable_alert_rule", {"rule_id": "nope"}))["data"]
    assert res["found"] is False


async def test_get_research_history_reads_snapshots():
    resources = _resources()
    await resources.research.scores.save_research_scores(
        [
            ResearchResult(
                symbol="NVDA",
                strategy="garp-v1",
                as_of=datetime(2026, 4, 1, tzinfo=UTC),
                score=72.0,
                confidence=0.9,
                model_version="research-v1.0.0",
            )
        ]
    )
    server = build_server(Settings(), resources=resources)
    data = _payload(
        await server.call_tool(
            "get_research_history",
            {"symbol": "nvda", "strategy": "GARP", "start": "2026-01-01", "end": "2026-06-01"},
        )
    )["data"]
    assert len(data["history"]) == 1
    assert data["history"][0]["score"] == 72.0


async def test_get_recent_filings_returns_events_newest_first():
    resources = _resources()
    await resources.catalysts.events.save_events(
        [
            Event(
                event_id="e1",
                symbol="NVDA",
                type="FILING_10Q",
                event_time=datetime(2026, 4, 1, tzinfo=UTC),
                title="10-Q",
            ),
            Event(
                event_id="e2",
                symbol="NVDA",
                type="FILING_8K",
                event_time=datetime(2026, 5, 1, tzinfo=UTC),
                title="8-K",
            ),
        ]
    )
    server = build_server(Settings(), resources=resources)
    data = _payload(
        await server.call_tool("get_recent_filings", {"symbol": "nvda", "lookback_days": 120})
    )["data"]
    assert [e["event_id"] for e in data["events"]] == ["e2", "e1"]
