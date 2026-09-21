"""Events backfill (``sv-events``): map securities to CIKs, then store each company's
recent 10-K/10-Q/8-K filings as events for catalyst correlation. Idempotent; requires
SV_SEC_USER_AGENT."""

from __future__ import annotations

import asyncio

from sentinel_vantage.core.config import Settings, get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.domain.market.universe import active_symbols, seed_universe
from sentinel_vantage.providers.fundamentals.sec import SECFundamentalsProvider
from sentinel_vantage.providers.news.sec_filings import SECFilingsProvider
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import (
    PostgresEventRepository,
    PostgresFundamentalRepository,
)

log = get_logger("events_backfill")
_REQUEST_SPACING_SECONDS = 0.2


async def _run(settings: Settings) -> None:
    db = Database(settings.postgres_dsn)
    await db.connect()
    sec = SECFundamentalsProvider(settings.sec_user_agent)
    filings = SECFilingsProvider(settings.sec_user_agent)
    fundamentals = PostgresFundamentalRepository(db)
    events_repo = PostgresEventRepository(db)
    try:
        await seed_universe(db)
        cik_map = await sec.get_cik_map()
        total = 0
        for sym in active_symbols():
            cik = cik_map.get(sym.replace(".", "-").upper()) or cik_map.get(sym.upper())
            if cik is None:
                log.warning("events.no_cik", symbol=sym)
                continue
            await fundamentals.set_cik(sym, cik)
            events = await filings.get_filing_events(cik, symbol=sym)
            await events_repo.save_events(events)
            total += len(events)
            log.info("events.symbol", symbol=sym, events=len(events))
            await asyncio.sleep(_REQUEST_SPACING_SECONDS)
        log.info("events.done", events=total)
    finally:
        await filings.close()
        await sec.close()
        await db.close()


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    if "set SV_SEC_USER_AGENT" in settings.sec_user_agent:
        raise SystemExit("SV_SEC_USER_AGENT is not set (SEC requires a UA with contact info).")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
