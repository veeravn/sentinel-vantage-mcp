"""Postgres-backed implementations of the trend service ports.

These satisfy the same BarRepository / ScoreRepository Protocols as the in-memory
versions, so swapping them in changes no domain or MCP code. JSONB columns are encoded
and decoded explicitly (json.dumps + ``::jsonb`` cast on write, json.loads on read) to
avoid relying on connection-level codecs.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta

from sentinel_vantage.core.timeutils import to_utc
from sentinel_vantage.domain.features.models import FeatureSet
from sentinel_vantage.domain.trend.models import TrendResult
from sentinel_vantage.providers.base import Bar
from sentinel_vantage.storage.postgres import Database


class PostgresBarRepository:
    def __init__(self, db: Database, *, benchmark_symbol: str = "SPY") -> None:
        self._db = db
        self.benchmark_symbol = benchmark_symbol

    async def list_active_universe(
        self, as_of: datetime, *, sector: str | None = None
    ) -> list[str]:
        rows = await self._db.pool.fetch(
            "SELECT symbol FROM security "
            "WHERE is_benchmark = FALSE "
            "  AND (active_from IS NULL OR active_from <= $1) "
            "  AND (active_to IS NULL OR active_to > $1) "
            "  AND ($2::text IS NULL OR sector = $2) "
            "ORDER BY symbol",
            as_of.date(),
            sector,
        )
        return [r["symbol"] for r in rows]

    async def get_daily_history(
        self, symbols: Sequence[str], as_of: datetime, *, lookback_days: int
    ) -> dict[str, list[Bar]]:
        if not symbols:
            return {}
        # Bound the scan generously in calendar days (>= lookback trading days).
        start = as_of - timedelta(days=lookback_days * 2)
        rows = await self._db.pool.fetch(
            "SELECT symbol, ts, open, high, low, close, volume, provider, feed "
            "FROM market_bar "
            "WHERE symbol = ANY($1::text[]) AND timeframe = '1d' "
            "  AND ts <= $2 AND ts >= $3 "
            "ORDER BY symbol, ts",
            list(symbols),
            as_of,
            start,
        )
        out: dict[str, list[Bar]] = {}
        for r in rows:
            out.setdefault(r["symbol"], []).append(
                Bar(
                    symbol=r["symbol"],
                    ts=r["ts"],
                    timeframe="1d",
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    provider=r["provider"],
                    feed=r["feed"],
                )
            )
        return {s: bars[-lookback_days:] for s, bars in out.items()}

    async def is_active(self, symbol: str, as_of: datetime) -> bool:
        row = await self._db.pool.fetchrow(
            "SELECT 1 FROM security "
            "WHERE symbol = $1 AND is_benchmark = FALSE "
            "  AND (active_from IS NULL OR active_from <= $2) "
            "  AND (active_to IS NULL OR active_to > $2)",
            symbol,
            as_of.date(),
        )
        return row is not None

    async def latest_bar_ts(self, *, timeframe: str = "1d") -> datetime | None:
        """Timestamp of the most recent stored bar (the session to score as-of)."""
        return await self._db.pool.fetchval(
            "SELECT max(ts) FROM market_bar WHERE timeframe = $1", timeframe
        )


class PostgresFeatureRepository:
    def __init__(self, db: Database, *, provider: str, feed: str) -> None:
        self._db = db
        self._provider = provider
        self._feed = feed

    async def save_feature_snapshots(
        self, features: Sequence[FeatureSet], *, feature_set_version: str
    ) -> None:
        if not features:
            return
        await self._db.pool.executemany(
            "INSERT INTO feature_snapshot "
            "(symbol, ts, feature_set_version, features, provider, feed) "
            "VALUES ($1, $2, $3, $4::jsonb, $5, $6) "
            "ON CONFLICT (symbol, feature_set_version, ts) DO NOTHING",
            [
                (
                    fs.symbol,
                    to_utc(fs.as_of),
                    feature_set_version,
                    fs.model_dump_json(),
                    self._provider,
                    self._feed,
                )
                for fs in features
            ],
        )


class PostgresScoreRepository:
    def __init__(self, db: Database, *, provider: str, feed: str) -> None:
        self._db = db
        self._provider = provider
        self._feed = feed

    async def save_trend_scores(self, results: Sequence[TrendResult]) -> None:
        if not results:
            return
        await self._db.pool.executemany(
            "INSERT INTO trend_score "
            "(symbol, horizon, ts, score, confidence, rank_percentile, "
            " reasons, risk_flags, metrics, factor_z, model_version, provider, feed) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb,$11,$12,$13) "
            "ON CONFLICT (symbol, horizon, model_version, ts) DO NOTHING",
            [
                (
                    r.symbol,
                    r.horizon,
                    to_utc(r.as_of),
                    r.score,
                    r.confidence,
                    r.rank_percentile,
                    json.dumps(r.reasons),
                    json.dumps(r.risk_flags),
                    json.dumps(r.metrics),
                    json.dumps(r.factor_z),
                    r.model_version,
                    self._provider,
                    self._feed,
                )
                for r in results
            ],
        )

    async def get_trend_history(
        self, symbol: str, *, horizon: str, start: datetime, end: datetime
    ) -> list[TrendResult]:
        rows = await self._db.pool.fetch(
            "SELECT symbol, horizon, ts, score, confidence, rank_percentile, "
            "       reasons, risk_flags, metrics, factor_z, model_version "
            "FROM trend_score "
            "WHERE symbol = $1 AND horizon = $2 AND ts BETWEEN $3 AND $4 "
            "ORDER BY ts",
            symbol,
            horizon,
            to_utc(start),
            to_utc(end),
        )
        return [
            TrendResult(
                symbol=r["symbol"],
                horizon=r["horizon"],
                as_of=r["ts"],
                score=r["score"],
                confidence=r["confidence"],
                rank_percentile=r["rank_percentile"],
                reasons=json.loads(r["reasons"]),
                risk_flags=json.loads(r["risk_flags"]),
                metrics=json.loads(r["metrics"]),
                factor_z=json.loads(r["factor_z"]),
                model_version=r["model_version"],
            )
            for r in rows
        ]
