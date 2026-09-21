"""Shared health model, surfaced by the ``get_status`` tool. A downed dependency degrades
the affected component rather than crashing the server."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from sentinel_vantage.core.config import Settings
from sentinel_vantage.storage.postgres import Database
from sentinel_vantage.storage.redis_store import RedisStore


class ComponentStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentHealth(BaseModel):
    name: str
    status: ComponentStatus
    detail: str | None = None


class SystemHealth(BaseModel):
    status: ComponentStatus
    components: list[ComponentHealth]
    environment: str
    feed: str


def _rollup(components: list[ComponentHealth]) -> ComponentStatus:
    statuses = {c.status for c in components}
    if ComponentStatus.DOWN in statuses:
        return ComponentStatus.DOWN
    if ComponentStatus.DEGRADED in statuses:
        return ComponentStatus.DEGRADED
    return ComponentStatus.OK


async def check_health(
    settings: Settings,
    *,
    db: Database | None = None,
    redis: RedisStore | None = None,
) -> SystemHealth:
    """Probe dependencies and return an aggregate. Never raises."""
    db = db or Database(settings.postgres_dsn)
    redis = redis or RedisStore(settings.redis_url)

    pg_ok = await db.ping()
    redis_ok = await redis.ping()

    components = [
        ComponentHealth(
            name="postgres",
            status=ComponentStatus.OK if pg_ok else ComponentStatus.DOWN,
            detail=None if pg_ok else "ping failed",
        ),
        ComponentHealth(
            name="redis",
            status=ComponentStatus.OK if redis_ok else ComponentStatus.DOWN,
            detail=None if redis_ok else "ping failed",
        ),
    ]

    return SystemHealth(
        status=_rollup(components),
        components=components,
        environment=settings.environment,
        feed=settings.feed_label,
    )
