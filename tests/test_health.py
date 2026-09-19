"""Health rollup logic and graceful degradation when dependencies are down."""

from __future__ import annotations

from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.health import (
    ComponentHealth,
    ComponentStatus,
    _rollup,
    check_health,
)


def test_rollup_prefers_worst_status():
    assert _rollup([_c(ComponentStatus.OK), _c(ComponentStatus.OK)]) == ComponentStatus.OK
    assert (
        _rollup([_c(ComponentStatus.OK), _c(ComponentStatus.DEGRADED)]) == ComponentStatus.DEGRADED
    )
    assert _rollup([_c(ComponentStatus.DEGRADED), _c(ComponentStatus.DOWN)]) == ComponentStatus.DOWN


async def test_check_health_never_raises_without_dependencies():
    # No Postgres/Redis running: pings fail, but the call returns a well-formed result.
    settings = Settings(
        postgres_dsn="postgresql://nope:nope@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    )
    health = await check_health(settings)
    assert health.status == ComponentStatus.DOWN
    names = {c.name for c in health.components}
    assert names == {"postgres", "redis"}
    assert health.feed == settings.feed_label


def _c(status: ComponentStatus) -> ComponentHealth:
    return ComponentHealth(name="x", status=status)
