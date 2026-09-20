"""SEC adapter: CIK map and XBRL fact extraction (offline via MockTransport)."""

from __future__ import annotations

from datetime import date

import httpx

from sentinel_vantage.providers.fundamentals.sec import SECFundamentalsProvider, extract_facts

_COMPANY_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-01-01",
                            "end": "2023-12-31",
                            "val": 383_000_000_000,
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-02-01",
                            "frame": "CY2023",
                        },
                        {
                            "start": "2022-01-01",
                            "end": "2022-12-31",
                            "val": 365_000_000_000,
                            "fy": 2022,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2023-02-01",
                        },
                        # Malformed entry (no val) must be skipped, not crash.
                        {"end": "2021-12-31", "filed": "2022-02-01"},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "end": "2023-12-31",
                            "val": 97_000_000_000,
                            "fy": 2023,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-02-01",
                        }
                    ]
                }
            },
            "IgnoredTag": {
                "units": {"USD": [{"end": "2023-12-31", "val": 1, "filed": "2024-02-01"}]}
            },
        }
    },
}


def test_extract_facts_filters_tags_and_skips_malformed():
    facts = extract_facts(_COMPANY_FACTS, "0000320193", ["Revenues", "NetIncomeLoss"])
    tags = {f.tag for f in facts}
    assert tags == {"Revenues", "NetIncomeLoss"}  # IgnoredTag excluded
    revenues = sorted((f for f in facts if f.tag == "Revenues"), key=lambda f: f.period_end)
    assert len(revenues) == 2  # malformed (no val) skipped
    latest = revenues[-1]
    assert latest.value == 383_000_000_000
    assert latest.period_end == date(2023, 12, 31)
    assert latest.filed_at == date(2024, 2, 1)  # point-in-time key preserved
    assert latest.form == "10-K"
    assert latest.source == "SEC-XBRL"


def test_extract_facts_reads_dei_taxonomy():
    # dei cover-page concepts (e.g. share count) must be reachable, not just us-gaap.
    companyfacts = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2023-12-31", "val": 100, "filed": "2024-02-01"}
                        ]
                    }
                }
            }
        }
    }
    facts = extract_facts(companyfacts, "C", ["EntityCommonStockSharesOutstanding"])
    assert len(facts) == 1
    assert facts[0].tag == "EntityCommonStockSharesOutstanding"
    assert facts[0].taxonomy == "dei"
    assert facts[0].value == 100


async def test_get_cik_map():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SECFundamentalsProvider("test-agent", client=client)
    cik_map = await provider.get_cik_map()
    assert cik_map["AAPL"] == "0000320193"  # zero-padded to 10 digits
    assert cik_map["MSFT"] == "0000789019"
    await provider.close()


async def test_get_facts_end_to_end():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "companyfacts/CIK0000320193.json" in request.url.path
        assert request.headers["User-Agent"] == "test-agent"  # SEC requires a UA
        return httpx.Response(200, json=_COMPANY_FACTS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = SECFundamentalsProvider("test-agent", client=client)
    facts = await provider.get_facts("0000320193", ["Revenues"])
    assert all(f.tag == "Revenues" for f in facts)
    assert len(facts) == 2
    await provider.close()
