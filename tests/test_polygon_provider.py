"""Polygon adapter: REST via httpx MockTransport, WebSocket via the pure parser."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from sentinel_vantage.providers.market_data.polygon import (
    PolygonMarketDataProvider,
    bar_from_agg,
    parse_ws_message,
)


def _provider(handler) -> PolygonMarketDataProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://mock")
    return PolygonMarketDataProvider("test-key", feed_mode="delayed", client=client)


def test_bar_from_agg_maps_fields_and_provenance():
    agg = {"t": 1_700_000_000_000, "o": 10, "h": 12, "l": 9, "c": 11, "v": 123456}
    bar = bar_from_agg("AAPL", agg, timeframe="1d", feed="polygon/delayed")
    assert bar.symbol == "AAPL"
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (10, 12, 9, 11, 123456)
    assert bar.feed == "polygon/delayed"
    assert bar.provider == "polygon"


async def test_get_bars_parses_aggregates_and_sends_api_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["apiKey"] = request.url.params.get("apiKey")
        seen["adjusted"] = request.url.params.get("adjusted")
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {"t": 1_700_000_000_000, "o": 100, "h": 105, "l": 99, "c": 104, "v": 1_000_000},
                    {
                        "t": 1_700_086_400_000,
                        "o": 104,
                        "h": 108,
                        "l": 103,
                        "c": 107,
                        "v": 1_200_000,
                    },
                ],
            },
        )

    provider = _provider(handler)
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 3, 2, tzinfo=UTC)
    bars = await provider.get_bars(["AAPL"], "1d", start, end)

    assert len(bars) == 2
    assert bars[0].close == 104 and bars[1].close == 107
    assert seen["apiKey"] == "test-key"
    assert seen["adjusted"] == "true"  # corporate-action adjusted
    assert seen["path"] == "/v2/aggs/ticker/AAPL/range/1/day/2026-03-01/2026-03-02"
    await provider.close()


async def test_get_bars_rejects_unknown_timeframe():
    provider = _provider(lambda r: httpx.Response(200, json={}))
    import pytest

    with pytest.raises(ValueError):
        await provider.get_bars(["AAPL"], "3s", datetime.now(UTC), datetime.now(UTC))
    await provider.close()


async def test_get_latest_quotes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "bid_price": 10.1,
                        "ask_price": 10.2,
                        "sip_timestamp": 1_700_000_000_000_000_000,
                    }
                ]
            },
        )

    provider = _provider(handler)
    quotes = await provider.get_latest_quotes(["AAPL"])
    assert quotes[0].bid == 10.1 and quotes[0].ask == 10.2
    assert quotes[0].feed == "polygon/delayed"
    await provider.close()


def test_parse_ws_message_extracts_minute_aggregates():
    raw = (
        '[{"ev":"status","status":"connected"},'
        '{"ev":"AM","sym":"NVDA","s":1700000000000,"e":1700000060000,'
        '"o":100,"h":101,"l":99.5,"c":100.8,"v":50000}]'
    )
    events = parse_ws_message(raw, feed="polygon/delayed")
    assert len(events) == 1  # status frame ignored
    ev = events[0]
    assert ev.bar.symbol == "NVDA"
    assert ev.bar.close == 100.8
    assert ev.bar.timeframe == "1m"
    assert ev.bar.feed == "polygon/delayed"


def test_parse_ws_message_handles_garbage():
    assert parse_ws_message("not json", feed="polygon/delayed") == []
    assert parse_ws_message('{"not":"a list"}', feed="polygon/delayed") == []


async def test_market_calendar_returns_weekday_sessions():
    provider = _provider(lambda r: httpx.Response(200, json={}))
    # 2026-03-02 is a Monday; 03-07/03-08 are the weekend.
    sessions = await provider.get_market_calendar(
        datetime(2026, 3, 2, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC)
    )
    dates = [s.date for s in sessions]
    assert dates == ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
    await provider.close()
