"""SEC EDGAR fundamentals adapter (no API key): the ticker->CIK map and the per-company
XBRL ``companyfacts`` document, each fact keeping its ``filed`` date for point-in-time
correctness. Requires a descriptive User-Agent; backs off on 429/5xx. Parsing is pure."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import httpx

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.providers.base import FundamentalFact, FundamentalsProvider

log = get_logger("sec")

DATA_BASE = "https://data.sec.gov"
WWW_BASE = "https://www.sec.gov"


def _to_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def extract_facts(
    companyfacts: dict[str, Any],
    cik: str,
    tags: Iterable[str],
    *,
    taxonomies: Sequence[str] = ("us-gaap", "dei"),
) -> list[FundamentalFact]:
    """Pure: pull the requested concept tags from a companyfacts document, scanning each
    taxonomy (us-gaap statement concepts plus the dei cover-page namespace)."""
    wanted = set(tags)
    all_facts = companyfacts.get("facts") or {}
    out: list[FundamentalFact] = []
    for taxonomy in taxonomies:
        facts_root = all_facts.get(taxonomy) or {}
        for tag, concept in facts_root.items():
            if tag not in wanted:
                continue
            for unit, entries in (concept.get("units") or {}).items():
                for e in entries:
                    end = _to_date(e.get("end"))
                    filed = _to_date(e.get("filed"))
                    if end is None or filed is None or e.get("val") is None:
                        continue
                    out.append(
                        FundamentalFact(
                            cik=cik,
                            taxonomy=taxonomy,
                            tag=tag,
                            unit=unit,
                            value=float(e["val"]),
                            period_start=_to_date(e.get("start")),
                            period_end=end,
                            fy=e.get("fy"),
                            fp=e.get("fp"),
                            form=e.get("form"),
                            filed_at=filed,
                            frame=e.get("frame"),
                        )
                    )
    return out


class SECFundamentalsProvider(FundamentalsProvider):
    name = "sec"

    def __init__(
        self,
        user_agent: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._client = client or httpx.AsyncClient(headers=self._headers, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, *, max_retries: int = 5) -> httpx.Response:
        delay = 1.0
        for attempt in range(max_retries + 1):
            # Set the UA per-request so it is present even with an injected client.
            resp = await self._client.get(url, headers=self._headers)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                resp.raise_for_status()
                return resp
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            log.warning("sec.retry", status=resp.status_code, wait=wait, url=url)
            await asyncio.sleep(min(wait, 30.0))
            delay = min(delay * 2, 30.0)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def get_cik_map(self) -> dict[str, str]:
        resp = await self._get(f"{WWW_BASE}/files/company_tickers.json")
        data = resp.json()
        return {
            str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10)
            for v in data.values()
            if v.get("ticker") and v.get("cik_str") is not None
        }

    async def get_company_facts(self, cik: str) -> dict[str, Any]:
        resp = await self._get(f"{DATA_BASE}/api/xbrl/companyfacts/CIK{cik}.json")
        return resp.json()

    async def get_facts(self, cik: str, tags: Iterable[str]) -> list[FundamentalFact]:
        raw = await self.get_company_facts(cik)
        return extract_facts(raw, cik, tags)
