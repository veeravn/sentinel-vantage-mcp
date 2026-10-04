"""Agent run records and the repository port used to log them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    kind: str
    goal: str
    backend: str
    model: str
    status: str  # answered | max_steps | token_budget | error
    answer: str
    error: str | None
    steps: int
    input_tokens: int
    output_tokens: int
    started_at: datetime
    finished_at: datetime
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


class AgentRunRepository(Protocol):
    async def save_run(self, run: AgentRun) -> None: ...

    async def list_runs(self, *, kind: str | None = None, limit: int = 20) -> list[AgentRun]: ...
