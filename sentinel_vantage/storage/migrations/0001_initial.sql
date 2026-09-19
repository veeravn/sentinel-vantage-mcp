-- Phase 1 schema: securities, market bars, feature/score snapshots.
-- Point-in-time by construction: fundamental/score history is append-only and never
-- overwritten, so past scores stay reproducible and backtests stay honest.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Slow-changing reference data. active_from/active_to give point-in-time membership and
-- keep delisted names in the historical universe (survivorship-bias guard).
CREATE TABLE IF NOT EXISTS security (
    symbol       TEXT PRIMARY KEY,
    name         TEXT,
    exchange     TEXT,
    sector       TEXT,
    industry     TEXT,
    is_etf       BOOLEAN NOT NULL DEFAULT FALSE,
    is_benchmark BOOLEAN NOT NULL DEFAULT FALSE,
    active_from  DATE,
    active_to    DATE,                       -- NULL = currently active
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS security_sector_idx ON security (sector);

-- Time-series market bars. MVP ingests Polygon adjusted bars; adj_close reserved for a
-- future raw+adjusted split. feed provenance stamped per row.
CREATE TABLE IF NOT EXISTS market_bar (
    symbol    TEXT NOT NULL,
    ts        TIMESTAMPTZ NOT NULL,
    timeframe TEXT NOT NULL,
    open      DOUBLE PRECISION NOT NULL,
    high      DOUBLE PRECISION NOT NULL,
    low       DOUBLE PRECISION NOT NULL,
    close     DOUBLE PRECISION NOT NULL,
    volume    DOUBLE PRECISION NOT NULL,
    adj_close DOUBLE PRECISION,
    provider  TEXT NOT NULL,
    feed      TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, ts)
);
SELECT create_hypertable('market_bar', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Stored feature inputs so scores can be reconstructed (design section 13).
CREATE TABLE IF NOT EXISTS feature_snapshot (
    symbol              TEXT NOT NULL,
    ts                  TIMESTAMPTZ NOT NULL,
    feature_set_version TEXT NOT NULL,
    features            JSONB NOT NULL,
    provider            TEXT NOT NULL,
    feed                TEXT NOT NULL,
    PRIMARY KEY (symbol, feature_set_version, ts)
);
SELECT create_hypertable('feature_snapshot', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Immutable trend-score snapshots (latest cache lives in Redis).
CREATE TABLE IF NOT EXISTS trend_score (
    symbol          TEXT NOT NULL,
    horizon         TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    score           DOUBLE PRECISION NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL,
    rank_percentile DOUBLE PRECISION,
    reasons         JSONB NOT NULL,
    risk_flags      JSONB NOT NULL,
    metrics         JSONB NOT NULL,
    factor_z        JSONB NOT NULL,
    model_version   TEXT NOT NULL,
    provider        TEXT NOT NULL,
    feed            TEXT NOT NULL,
    PRIMARY KEY (symbol, horizon, model_version, ts)
);
SELECT create_hypertable('trend_score', 'ts', if_not_exists => TRUE, migrate_data => TRUE);
