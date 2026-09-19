-- Phase 2 schema: point-in-time fundamentals and per-strategy research scores.

-- Link securities to their SEC CIK (populated by the fundamentals backfill).
ALTER TABLE security ADD COLUMN IF NOT EXISTS cik TEXT;
CREATE INDEX IF NOT EXISTS security_cik_idx ON security (cik);

-- Append-only XBRL facts. A restatement is a new row with a later filed_at, never an
-- overwrite, so point-in-time reads (filed_at <= as_of) stay honest for backtests.
CREATE TABLE IF NOT EXISTS fundamental_fact (
    id           BIGSERIAL PRIMARY KEY,
    cik          TEXT NOT NULL,
    taxonomy     TEXT NOT NULL DEFAULT 'us-gaap',
    tag          TEXT NOT NULL,
    unit         TEXT NOT NULL,
    value        DOUBLE PRECISION NOT NULL,
    period_start DATE,
    period_end   DATE NOT NULL,
    fy           INTEGER,
    fp           TEXT,
    form         TEXT,
    filed_at     DATE NOT NULL,
    frame        TEXT,
    source       TEXT NOT NULL DEFAULT 'SEC-XBRL'
);
-- Uniqueness across the natural key (period_start is nullable for instant facts).
CREATE UNIQUE INDEX IF NOT EXISTS fundamental_fact_uq ON fundamental_fact
    (cik, taxonomy, tag, unit, COALESCE(period_start, DATE '1900-01-01'), period_end, filed_at);
CREATE INDEX IF NOT EXISTS fundamental_fact_lookup ON fundamental_fact (cik, tag, filed_at);

-- Immutable per-strategy research-score snapshots (latest cache lives in Redis).
CREATE TABLE IF NOT EXISTS strategy_score (
    symbol             TEXT NOT NULL,
    strategy           TEXT NOT NULL,
    ts                 TIMESTAMPTZ NOT NULL,
    score              DOUBLE PRECISION NOT NULL,
    confidence         DOUBLE PRECISION NOT NULL,
    rank_percentile    DOUBLE PRECISION,
    factors            JSONB NOT NULL,
    penalties          JSONB NOT NULL,
    positive_reasons   JSONB NOT NULL,
    negative_reasons   JSONB NOT NULL,
    hard_gate_failures JSONB NOT NULL,
    model_version      TEXT NOT NULL,
    provider           TEXT NOT NULL,
    feed               TEXT NOT NULL,
    PRIMARY KEY (symbol, strategy, model_version, ts)
);
SELECT create_hypertable('strategy_score', 'ts', if_not_exists => TRUE, migrate_data => TRUE);
