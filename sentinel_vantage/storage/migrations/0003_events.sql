-- Phase 3 schema: structured market events (filings, earnings, corporate actions, news).
-- Stored as metadata/identifiers/URLs, not licensed full text (design section 8.3).

CREATE TABLE IF NOT EXISTS event (
    source     TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    symbol     TEXT,
    cik        TEXT,
    type       TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    title      TEXT,
    url        TEXT,
    metadata   JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (source, event_id)
);
CREATE INDEX IF NOT EXISTS event_symbol_time_idx ON event (symbol, event_time);
CREATE INDEX IF NOT EXISTS event_cik_time_idx ON event (cik, event_time);
