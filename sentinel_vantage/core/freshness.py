"""Data freshness: how old the newest stored daily bar is, surfaced by ``get_status`` so
stale data (e.g. ingestion stopped) is visible instead of silently scored."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from sentinel_vantage.core.timeutils import isoformat_z, to_utc


class DataFreshness(BaseModel):
    latest_bar_at: str | None
    age_days: int | None
    stale_after_days: int
    stale: bool
    warning: str | None = None


def assess_freshness(
    latest_bar_ts: datetime | None, now: datetime, *, stale_after_days: int
) -> DataFreshness:
    """Age is calendar days from the latest bar's session date to today (UTC). The default
    threshold tolerates a weekend plus a market holiday before the next backfill."""
    if latest_bar_ts is None:
        return DataFreshness(
            latest_bar_at=None,
            age_days=None,
            stale_after_days=stale_after_days,
            stale=True,
            warning="No market data is loaded; run sv-backfill.",
        )
    latest = to_utc(latest_bar_ts)
    age = max(0, (to_utc(now).date() - latest.date()).days)
    stale = age > stale_after_days
    warning = (
        f"Market data is {age} days old (latest session {latest.date().isoformat()}); "
        "scores reflect that session, not today. Check that the daily backfill is running."
        if stale
        else None
    )
    return DataFreshness(
        latest_bar_at=isoformat_z(latest),
        age_days=age,
        stale_after_days=stale_after_days,
        stale=stale,
        warning=warning,
    )
