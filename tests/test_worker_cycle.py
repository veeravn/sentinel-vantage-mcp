"""Worker scoring cycle and backfill store logic (offline)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from conftest import make_daily_bars

from sentinel_vantage.apps.market_worker.scoring import run_scoring_cycle
from sentinel_vantage.core.versioning import FEATURE_SET_VERSION
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.providers.market_data.polygon import PolygonMarketDataProvider
from sentinel_vantage.storage.memory import (
    InMemoryBarRepository,
    InMemoryFeatureRepository,
    InMemoryScoreRepository,
)


def _repo() -> InMemoryBarRepository:
    return InMemoryBarRepository(
        {
            "SPY": make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70),
            "HOT": make_daily_bars("HOT", [100.0] * 69 + [118.0], [1_000_000.0] * 69 + [5e6]),
            "MID": make_daily_bars("MID", [100.0] * 69 + [101.0], [1_000_000.0] * 70),
        }
    )


async def test_cycle_persists_features_and_scores():
    bars = _repo()
    scores = InMemoryScoreRepository()
    features = InMemoryFeatureRepository()
    svc = TrendService(bars, scores=scores, features=features)
    as_of = await bars.latest_bar_ts()

    scan = await run_scoring_cycle(svc, None, horizon="1d", as_of=as_of)

    assert [r.symbol for r in scan.results][0] == "HOT"
    # Feature snapshots persisted for every eligible symbol, tagged with the version.
    assert {fs.symbol for _, fs in features.saved} == {"HOT", "MID"}
    assert all(ver == FEATURE_SET_VERSION for ver, _ in features.saved)
    # Score snapshots persisted (queryable as history).
    hist = await scores.get_trend_history(
        "HOT", horizon="1d", start=as_of.replace(hour=0), end=as_of
    )
    assert len(hist) == 1


async def test_backfill_store_maps_and_upserts():
    # get_bars via MockTransport -> store_bars would need a DB; here assert parsing only.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"t": 1_700_000_000_000, "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 1000},
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock")
    provider = PolygonMarketDataProvider("k", feed_mode="delayed", client=client)
    bars = await provider.get_bars(
        ["AAPL"], "1d", datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert bars[0].symbol == "AAPL" and bars[0].close == 10.5
    assert bars[0].feed == "polygon/delayed"
    await provider.close()
