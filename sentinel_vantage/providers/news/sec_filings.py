"""SEC filings as structured events.

Uses SEC's public ``submissions`` API (no key) to turn a company's recent material
filings (10-K, 10-Q, 8-K) into normalized Events. 8-Ks in particular are the "material
event" filing and the most catalyst-relevant. We store identifiers, form type, filing
time, and a link — not licensed full text (design section 8.3).

Parsing is a pure function so it is unit-testable without network access.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.timeutils import to_utc
from sentinel_vantage.domain.catalysts.models import Event

log = get_logger("sec_filings")

DATA_BASE = "https://data.sec.gov"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

# Material forms we keep, mapped to event types.
FORM_TYPE = {
    "10-K": "FILING_10K",
    "10-K/A": "FILING_10K",
    "10-Q": "FILING_10Q",
    "10-Q/A": "FILING_10Q",
    "8-K": "FILING_8K",
    "8-K/A": "FILING_8K",
}


def _event_time(acceptance: str | None, filing_date: str | None) -> datetime | None:
    if acceptance:
        try:
            return to_utc(datetime.fromisoformat(acceptance.replace("Z", "+00:00")))
        except ValueError:
            pass
    if filing_date:
        try:
            return datetime.fromisoformat(filing_date).replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _filing_url(cik: str, accession: str, primary_doc: str | None) -> str:
    acc_nodash = accession.replace("-", "")
    base = f"{ARCHIVES}/{int(cik)}/{acc_nodash}"
    return f"{base}/{primary_doc}" if primary_doc else f"{base}/"


def parse_submissions(data: dict[str, Any], cik: str, symbol: str | None) -> list[Event]:
    """Pure: turn a submissions document's recent filings into material-form Events."""
    recent = ((data.get("filings") or {}).get("recent")) or {}
    accessions = recent.get("accessionNumber") or []
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    acceptance = recent.get("acceptanceDateTime") or []
    primary_docs = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []

    events: list[Event] = []
    for i, accession in enumerate(accessions):
        form = forms[i] if i < len(forms) else None
        etype = FORM_TYPE.get(form or "")
        if etype is None:
            continue
        when = _event_time(
            acceptance[i] if i < len(acceptance) else None,
            filing_dates[i] if i < len(filing_dates) else None,
        )
        if when is None:
            continue
        desc = descriptions[i] if i < len(descriptions) else None
        events.append(
            Event(
                event_id=accession,
                source="SEC",
                symbol=symbol,
                cik=cik,
                type=etype,
                event_time=when,
                title=f"{form}{f' — {desc}' if desc else ''}",
                url=_filing_url(cik, accession, primary_docs[i] if i < len(primary_docs) else None),
                metadata={"form": form},
            )
        )
    return events


class SECFilingsProvider:
    name = "sec-filings"

    def __init__(self, user_agent: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._client = client or httpx.AsyncClient(headers=self._headers, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, url: str, *, max_retries: int = 5) -> httpx.Response:
        delay = 1.0
        for attempt in range(max_retries + 1):
            resp = await self._client.get(url, headers=self._headers)
            if resp.status_code not in (429, 500, 502, 503, 504) or attempt == max_retries:
                resp.raise_for_status()
                return resp
            ra = resp.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else delay
            log.warning("sec_filings.retry", status=resp.status_code, wait=wait)
            await asyncio.sleep(min(wait, 30.0))
            delay = min(delay * 2, 30.0)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def get_filing_events(self, cik: str, *, symbol: str | None = None) -> list[Event]:
        resp = await self._get(f"{DATA_BASE}/submissions/CIK{cik}.json")
        return parse_submissions(resp.json(), cik, symbol)
