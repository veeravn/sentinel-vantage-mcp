-- Phase 5 schema: watchlists, alert rules, and alert events.

CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_id TEXT PRIMARY KEY,
    owner        TEXT,
    name         TEXT NOT NULL,
    symbols      JSONB NOT NULL DEFAULT '[]',
    settings     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Structured, validated rules (not free-form text) so they can be replayed.
CREATE TABLE IF NOT EXISTS alert_rule (
    rule_id      TEXT PRIMARY KEY,
    name         TEXT,
    owner        TEXT,
    symbols      JSONB NOT NULL DEFAULT '[]',
    watchlist_id TEXT,
    rule         JSONB NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Triggered alerts, with the evaluated metric values kept for audit.
CREATE TABLE IF NOT EXISTS alert_event (
    event_id    TEXT PRIMARY KEY,
    rule_id     TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    as_of       TIMESTAMPTZ NOT NULL,
    severity    TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    metrics     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS alert_event_rule_symbol_idx ON alert_event (rule_id, symbol, created_at);
CREATE INDEX IF NOT EXISTS alert_event_created_idx ON alert_event (created_at);
