"""Ports for watchlist, rule, and alert-event storage."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentinel_vantage.domain.alerts.models import AlertEvent, AlertRule, Watchlist


@runtime_checkable
class WatchlistRepository(Protocol):
    async def save_watchlist(self, watchlist: Watchlist) -> None: ...
    async def get_watchlist(self, watchlist_id: str) -> Watchlist | None: ...
    async def delete_watchlist(self, watchlist_id: str) -> bool: ...


@runtime_checkable
class AlertRuleRepository(Protocol):
    async def save_rule(self, rule: AlertRule) -> None: ...
    async def get_rule(self, rule_id: str) -> AlertRule | None: ...
    async def list_active_rules(self) -> list[AlertRule]: ...
    async def delete_rule(self, rule_id: str) -> bool: ...


@runtime_checkable
class AlertEventRepository(Protocol):
    async def save_event(self, event: AlertEvent) -> None: ...

    async def recent_for(
        self, rule_id: str, symbol: str, *, since: datetime
    ) -> list[AlertEvent]: ...

    async def list_events(
        self,
        *,
        since: datetime,
        symbols: Sequence[str] | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[AlertEvent]: ...
