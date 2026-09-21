"""Time helpers. Convention: all timestamps are stored and compared in UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to timezone-aware UTC (naive datetimes are assumed UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def isoformat_z(dt: datetime) -> str:
    """ISO-8601 in UTC with a trailing ``Z`` (the form used in MCP output)."""
    return to_utc(dt).isoformat().replace("+00:00", "Z")
