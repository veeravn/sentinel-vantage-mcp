-- Agent run log: one row per agent run, with the tool-call trace kept for audit.

CREATE TABLE IF NOT EXISTS agent_run (
    run_id        TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    goal          TEXT NOT NULL,
    backend       TEXT NOT NULL,
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,
    answer        TEXT NOT NULL DEFAULT '',
    error         TEXT,
    steps         INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    tool_trace    JSONB NOT NULL DEFAULT '[]',
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_run_started_idx ON agent_run (started_at DESC);
CREATE INDEX IF NOT EXISTS agent_run_kind_idx ON agent_run (kind, started_at DESC);
