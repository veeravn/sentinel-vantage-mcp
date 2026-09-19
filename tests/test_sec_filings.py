"""SEC filings -> events: parsing and the provider (offline)."""

from __future__ import annotations

import httpx

from sentinel_vantage.providers.news.sec_filings import SECFilingsProvider, parse_submissions

_SUBMISSIONS = {
    "cik": "320193",
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-24-000010",
                "0000320193-24-000008",
                "0000320193-24-000004",
            ],
            "form": ["8-K", "10-K", "4"],  # 4 (insider) is non-material -> skipped
            "filingDate": ["2024-05-02", "2024-02-01", "2024-01-15"],
            "acceptanceDateTime": ["2024-05-02T18:01:12.000Z", "2024-02-01T16:30:00.000Z", ""],
            "primaryDocument": ["ex99.htm", "aapl-20231230.htm", "form4.xml"],
            "primaryDocDescription": ["Earnings release", "10-K", "Form 4"],
        }
    },
}


def test_parse_submissions_keeps_material_forms():
    events = parse_submissions(_SUBMISSIONS, "0000320193", "AAPL")
    types = [e.type for e in events]
    assert types == ["FILING_8K", "FILING_10K"]  # Form 4 dropped
    ek = events[0]
    assert ek.event_id == "0000320193-24-000010"
    assert ek.symbol == "AAPL" and ek.cik == "0000320193"
    assert ek.event_time.year == 2024 and ek.event_time.month == 5
    assert "320193" in ek.url and ek.url.endswith("ex99.htm")


async def test_provider_fetches_and_parses():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "submissions/CIK0000320193.json" in request.url.path
        assert request.headers["User-Agent"] == "ua"
        return httpx.Response(200, json=_SUBMISSIONS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SECFilingsProvider("ua", client=client)
    events = await provider.get_filing_events("0000320193", symbol="AAPL")
    assert {e.type for e in events} == {"FILING_8K", "FILING_10K"}
    await provider.close()
