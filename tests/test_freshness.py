"""Data-freshness assessment and its surfacing through get_status."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from conftest import make_daily_bars

from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.freshness import assess_freshness
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.memory import InMemoryBarRepository

NOW = datetime(2026, 10, 7, 7, 0, tzinfo=UTC)
SESSION = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)  # Friday


def test_fresh_within_threshold():
    f = assess_freshness(datetime(2026, 10, 6, 4, 0, tzinfo=UTC), NOW, stale_after_days=4)
    assert (f.age_days, f.stale, f.warning) == (1, False, None)
    assert f.latest_bar_at == "2026-10-06T04:00:00Z"


def test_weekend_and_holiday_tolerated_then_stale():
    assert not assess_freshness(
        SESSION, datetime(2026, 10, 6, tzinfo=UTC), stale_after_days=4
    ).stale
    stale = assess_freshness(SESSION, NOW, stale_after_days=4)
    assert stale.age_days == 5 and stale.stale
    assert "5 days old" in stale.warning and "2026-10-02" in stale.warning


def test_three_week_gap_reported():
    f = assess_freshness(datetime(2026, 9, 18, 4, 0, tzinfo=UTC), NOW, stale_after_days=4)
    assert f.age_days == 19 and f.stale


def test_no_bars_is_stale():
    f = assess_freshness(None, NOW, stale_after_days=4)
    assert f.stale and f.age_days is None and "sv-backfill" in f.warning


def test_future_timestamp_clamps_to_zero_age():
    f = assess_freshness(NOW + timedelta(days=1), NOW, stale_after_days=4)
    assert f.age_days == 0 and not f.stale


async def _status(bars: InMemoryBarRepository, **settings) -> dict:
    server = build_server(Settings(**settings), trend=TrendService(bars))
    result = await server.call_tool("get_status", {})
    assert not result.is_error
    return json.loads(result.content[0].text)["data"]["data_freshness"]


async def test_get_status_reports_stale_data():
    bars = InMemoryBarRepository({"SPY": make_daily_bars("SPY", [100.0] * 5, start="2026-03-02")})
    f = await _status(bars)
    assert f["stale"] is True and f["age_days"] > 4 and "days old" in f["warning"]


async def test_get_status_reports_fresh_data_and_honors_threshold():
    start = (utcnow() - timedelta(days=4)).date().isoformat()
    bars = InMemoryBarRepository({"SPY": make_daily_bars("SPY", [100.0], start=start)})
    assert (await _status(bars))["stale"] is False
    assert (await _status(bars, data_stale_after_days=2))["stale"] is True


async def test_get_status_with_no_bars():
    f = await _status(InMemoryBarRepository({}))
    assert f["stale"] is True and f["latest_bar_at"] is None


async def test_get_status_survives_database_error():
    server = build_server(
        Settings(
            postgres_dsn="postgresql://nope:nope@127.0.0.1:1/none",
            redis_url="redis://127.0.0.1:1/0",
        )
    )
    result = await server.call_tool("get_status", {})
    assert not result.is_error
    assert json.loads(result.content[0].text)["data"]["data_freshness"]["stale"] is None
