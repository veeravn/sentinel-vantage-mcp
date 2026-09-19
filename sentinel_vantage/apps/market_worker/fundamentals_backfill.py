"""Fundamentals backfill: map securities to CIKs and ingest their XBRL facts.

Entry point ``sv-fundamentals``: fetch SEC's ticker->CIK map, set each active
security's CIK, then pull its companyfacts (one request per symbol) and store the
tags in ``domain.research.tags.ALL_TAGS`` as point-in-time facts. Idempotent.

Requires SV_SEC_USER_AGENT (SEC needs a descriptive User-Agent with contact info).
"""

from __future__ import annotations

import asyncio

from sentinel_vantage.core.config import Settings, get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger
from sentinel_vantage.domain.market.universe import active_symbols, seed_universe
from sentinel_vantage.domain.research.tags import ALL_TAGS
from sentinel_vantage.providers.fundamentals.sec import SECFundamentalsProvider
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.postgres_repos import PostgresFundamentalRepository

log = get_logger("fundamentals_backfill")

# Polite pause between companyfacts requests (SEC rate-limits aggressive clients).
_REQUEST_SPACING_SECONDS = 0.2


async def _run(settings: Settings) -> None:
    db = Database(settings.postgres_dsn)
    await db.connect()
    provider = SECFundamentalsProvider(settings.sec_user_agent)
    repo = PostgresFundamentalRepository(db)
    try:
        await seed_universe(db)
        cik_map = await provider.get_cik_map()
        symbols = active_symbols()
        stored = 0
        for sym in symbols:
            cik = cik_map.get(sym.replace(".", "-").upper()) or cik_map.get(sym.upper())
            if cik is None:
                log.warning("fundamentals.no_cik", symbol=sym)
                continue
            await repo.set_cik(sym, cik)
            facts = await provider.get_facts(cik, ALL_TAGS)
            await repo.save_facts(facts)
            stored += len(facts)
            log.info("fundamentals.symbol", symbol=sym, cik=cik, facts=len(facts))
            await asyncio.sleep(_REQUEST_SPACING_SECONDS)
        log.info("fundamentals.done", symbols=len(symbols), facts=stored)
    finally:
        await provider.close()
        await db.close()


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    if "set SV_SEC_USER_AGENT" in settings.sec_user_agent:
        raise SystemExit(
            "SV_SEC_USER_AGENT is not set. SEC requires a descriptive User-Agent with "
            "contact info, e.g. 'Your Name your@email'."
        )
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
