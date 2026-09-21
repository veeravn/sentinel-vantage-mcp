"""Postgres-backed watchlist, alert-rule, and alert-event repositories."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime

from sentinel_vantage.core.timeutils import to_utc
from sentinel_vantage.domain.alerts.models import (
    AlertEvent,
    AlertRule,
    RuleDSL,
    Watchlist,
)
from sentinel_vantage.storage.postgres import Database


class PostgresWatchlistRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_watchlist(self, wl: Watchlist) -> None:
        await self._db.pool.execute(
            "INSERT INTO watchlist (watchlist_id, owner, name, symbols, settings, created_at) "
            "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6) "
            "ON CONFLICT (watchlist_id) DO UPDATE SET "
            "  owner=EXCLUDED.owner, name=EXCLUDED.name, symbols=EXCLUDED.symbols, "
            "  settings=EXCLUDED.settings",
            wl.watchlist_id,
            wl.owner,
            wl.name,
            json.dumps(wl.symbols),
            json.dumps(wl.settings),
            to_utc(wl.created_at),
        )

    async def get_watchlist(self, watchlist_id: str) -> Watchlist | None:
        r = await self._db.pool.fetchrow(
            "SELECT watchlist_id, owner, name, symbols, settings, created_at "
            "FROM watchlist WHERE watchlist_id = $1",
            watchlist_id,
        )
        if r is None:
            return None
        return Watchlist(
            watchlist_id=r["watchlist_id"],
            owner=r["owner"],
            name=r["name"],
            symbols=json.loads(r["symbols"]),
            settings=json.loads(r["settings"]),
            created_at=r["created_at"],
        )

    async def delete_watchlist(self, watchlist_id: str) -> bool:
        status = await self._db.pool.execute(
            "DELETE FROM watchlist WHERE watchlist_id = $1", watchlist_id
        )
        return _rows_affected(status) > 0


class PostgresAlertRuleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_rule(self, rule: AlertRule) -> None:
        await self._db.pool.execute(
            "INSERT INTO alert_rule (rule_id, name, owner, symbols, watchlist_id, rule, "
            " severity, active, created_at) "
            "VALUES ($1,$2,$3,$4::jsonb,$5,$6::jsonb,$7,$8,$9) "
            "ON CONFLICT (rule_id) DO UPDATE SET "
            "  name=EXCLUDED.name, symbols=EXCLUDED.symbols, watchlist_id=EXCLUDED.watchlist_id, "
            "  rule=EXCLUDED.rule, severity=EXCLUDED.severity, active=EXCLUDED.active",
            rule.rule_id,
            rule.name,
            rule.owner,
            json.dumps(rule.symbols),
            rule.watchlist_id,
            rule.rule.model_dump_json(),
            rule.severity,
            rule.active,
            to_utc(rule.created_at),
        )

    async def get_rule(self, rule_id: str) -> AlertRule | None:
        r = await self._db.pool.fetchrow(
            "SELECT rule_id, name, owner, symbols, watchlist_id, rule, severity, active, "
            "       created_at FROM alert_rule WHERE rule_id = $1",
            rule_id,
        )
        return _rule_from_row(r) if r is not None else None

    async def list_active_rules(self) -> list[AlertRule]:
        rows = await self._db.pool.fetch(
            "SELECT rule_id, name, owner, symbols, watchlist_id, rule, severity, active, "
            "       created_at FROM alert_rule WHERE active = TRUE ORDER BY created_at"
        )
        return [_rule_from_row(r) for r in rows]

    async def delete_rule(self, rule_id: str) -> bool:
        status = await self._db.pool.execute("DELETE FROM alert_rule WHERE rule_id = $1", rule_id)
        return _rows_affected(status) > 0


class PostgresAlertEventRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_event(self, event: AlertEvent) -> None:
        await self._db.pool.execute(
            "INSERT INTO alert_event (event_id, rule_id, symbol, as_of, severity, fingerprint, "
            " metrics, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8) "
            "ON CONFLICT (event_id) DO NOTHING",
            event.event_id,
            event.rule_id,
            event.symbol,
            to_utc(event.as_of),
            event.severity,
            event.fingerprint,
            json.dumps(event.metrics),
            to_utc(event.created_at),
        )

    async def recent_for(self, rule_id: str, symbol: str, *, since: datetime) -> list[AlertEvent]:
        rows = await self._db.pool.fetch(
            "SELECT event_id, rule_id, symbol, as_of, severity, fingerprint, metrics, created_at "
            "FROM alert_event WHERE rule_id = $1 AND symbol = $2 AND created_at >= $3 "
            "ORDER BY created_at DESC",
            rule_id,
            symbol,
            to_utc(since),
        )
        return [_event_from_row(r) for r in rows]

    async def list_events(
        self,
        *,
        since: datetime,
        symbols: Sequence[str] | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[AlertEvent]:
        rows = await self._db.pool.fetch(
            "SELECT event_id, rule_id, symbol, as_of, severity, fingerprint, metrics, created_at "
            "FROM alert_event WHERE created_at >= $1 "
            "  AND ($2::text[] IS NULL OR symbol = ANY($2::text[])) "
            "  AND ($3::text IS NULL OR severity = $3) "
            "ORDER BY created_at DESC LIMIT $4",
            to_utc(since),
            list(symbols) if symbols else None,
            severity,
            limit,
        )
        return [_event_from_row(r) for r in rows]


def _rows_affected(status: str) -> int:
    """Parse an asyncpg command tag (e.g. "DELETE 1") into an affected-row count."""
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


def _rule_from_row(r) -> AlertRule:
    return AlertRule(
        rule_id=r["rule_id"],
        name=r["name"],
        owner=r["owner"],
        symbols=json.loads(r["symbols"]),
        watchlist_id=r["watchlist_id"],
        rule=RuleDSL.model_validate_json(r["rule"]),
        severity=r["severity"],
        active=r["active"],
        created_at=r["created_at"],
    )


def _event_from_row(r) -> AlertEvent:
    return AlertEvent(
        event_id=r["event_id"],
        rule_id=r["rule_id"],
        symbol=r["symbol"],
        as_of=r["as_of"],
        severity=r["severity"],
        fingerprint=r["fingerprint"],
        metrics=json.loads(r["metrics"]),
        created_at=r["created_at"],
    )
