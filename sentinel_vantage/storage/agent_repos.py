"""Postgres-backed agent run log."""

from __future__ import annotations

import json

from sentinel_vantage.agent.runs import AgentRun
from sentinel_vantage.core.timeutils import to_utc
from sentinel_vantage.storage.postgres import Database


class PostgresAgentRunRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def save_run(self, run: AgentRun) -> None:
        await self._db.pool.execute(
            "INSERT INTO agent_run (run_id, kind, goal, backend, model, status, answer, error, "
            " steps, input_tokens, output_tokens, tool_trace, started_at, finished_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14) "
            "ON CONFLICT (run_id) DO NOTHING",
            run.run_id,
            run.kind,
            run.goal,
            run.backend,
            run.model,
            run.status,
            run.answer,
            run.error,
            run.steps,
            run.input_tokens,
            run.output_tokens,
            json.dumps(run.tool_trace),
            to_utc(run.started_at),
            to_utc(run.finished_at),
        )

    async def list_runs(self, *, kind: str | None = None, limit: int = 20) -> list[AgentRun]:
        rows = await self._db.pool.fetch(
            "SELECT run_id, kind, goal, backend, model, status, answer, error, steps, "
            " input_tokens, output_tokens, tool_trace, started_at, finished_at "
            "FROM agent_run WHERE ($1::text IS NULL OR kind = $1) "
            "ORDER BY started_at DESC LIMIT $2",
            kind,
            limit,
        )
        return [
            AgentRun(
                **{k: v for k, v in dict(r).items() if k != "tool_trace"},
                tool_trace=json.loads(r["tool_trace"]),
            )
            for r in rows
        ]
