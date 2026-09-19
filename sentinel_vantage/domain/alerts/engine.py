"""Alert engine — evaluate active rules and emit deduplicated alert events.

Runs in the scheduler, independent of any MCP client (design section 16). For each
active rule it resolves the referenced metrics for the rule's symbols, evaluates the
DSL, and — subject to a per-(rule, symbol) cooldown — persists an alert event with the
evaluated values for audit.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.domain.alerts.evaluator import evaluate_rule, evaluated_metrics
from sentinel_vantage.domain.alerts.models import AlertEvent, AlertRule
from sentinel_vantage.domain.alerts.ports import (
    AlertEventRepository,
    AlertRuleRepository,
    WatchlistRepository,
)
from sentinel_vantage.domain.alerts.resolver import MetricResolver

log = get_logger("alert_engine")


class AlertEngine:
    def __init__(
        self,
        rules: AlertRuleRepository,
        events: AlertEventRepository,
        resolver: MetricResolver,
        *,
        watchlists: WatchlistRepository | None = None,
        clock: Callable[[], datetime] = utcnow,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.rules = rules
        self.events = events
        self.resolver = resolver
        self.watchlists = watchlists
        self._clock = clock
        self._id = id_factory

    async def _symbols_for(self, rule: AlertRule) -> list[str]:
        if rule.symbols:
            return rule.symbols
        if rule.watchlist_id and self.watchlists is not None:
            wl = await self.watchlists.get_watchlist(rule.watchlist_id)
            return list(wl.symbols) if wl else []
        return []

    async def run_once(self, as_of: datetime | None = None) -> list[AlertEvent]:
        as_of = as_of or self._clock()
        created: list[AlertEvent] = []
        for rule in await self.rules.list_active_rules():
            symbols = await self._symbols_for(rule)
            if not symbols:
                continue
            referenced = rule.rule.referenced_metrics()
            metric_map = await self.resolver.resolve(symbols, as_of, metrics=referenced)

            cooldown_since = as_of - timedelta(hours=rule.rule.cooldown_hours)
            for symbol in symbols:
                metrics = metric_map.get(symbol, {})
                if not evaluate_rule(rule.rule, metrics):
                    continue
                if await self.events.recent_for(rule.rule_id, symbol, since=cooldown_since):
                    continue  # within cooldown -> deduplicated
                event = AlertEvent(
                    event_id=self._id(),
                    rule_id=rule.rule_id,
                    symbol=symbol,
                    as_of=as_of,
                    severity=rule.severity,
                    fingerprint=f"{rule.rule_id}|{symbol}",
                    metrics=evaluated_metrics(rule.rule, metrics),
                    created_at=as_of,
                )
                await self.events.save_event(event)
                created.append(event)
        if created:
            log.info("alert_engine.fired", count=len(created))
        return created
