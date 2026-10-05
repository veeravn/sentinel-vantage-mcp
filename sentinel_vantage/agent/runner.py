"""The agent loop: call the model, execute requested tools, feed results back, and repeat
until the model answers or a budget (steps, tokens) is exhausted."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

from sentinel_vantage.agent.grounding import GroundingReport, check_grounding
from sentinel_vantage.agent.llm import LLMClient, Message, ToolCall, ToolResult, ToolSpec
from sentinel_vantage.agent.prompts import SYSTEM_PROMPT
from sentinel_vantage.agent.runs import AgentRun, AgentRunRepository
from sentinel_vantage.agent.tools import WRITE_TOOLS, ToolSource
from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.core.timeutils import utcnow

log = get_logger("agent")

StopReason = Literal["answered", "max_steps", "token_budget"]


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    is_error: bool
    output_chars: int
    output_preview: str = ""


@dataclass
class AgentResult:
    answer: str
    stop_reason: StopReason
    steps: int
    input_tokens: int
    output_tokens: int
    tool_trace: list[ToolTrace] = field(default_factory=list)
    run_id: str = ""
    tool_outputs: list[str] = field(default_factory=list, repr=False)
    grounding: GroundingReport | None = None


class AgentRunner:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolSource,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        max_steps: int = 8,
        max_total_tokens: int = 100_000,
        max_output_tokens: int = 2048,
        max_tool_output_chars: int = 20_000,
        allow_writes: bool = False,
        allowed_tools: frozenset[str] | None = None,
        runs: AgentRunRepository | None = None,
        backend: str = "",
        grounding_retries: int = 1,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._system = system_prompt
        self._max_steps = max_steps
        self._max_total_tokens = max_total_tokens
        self._max_output_tokens = max_output_tokens
        self._max_tool_chars = max_tool_output_chars
        self._allow_writes = allow_writes
        self._allowed = allowed_tools
        self._runs = runs
        self._backend = backend
        self._grounding_retries = grounding_retries

    def _permitted(self, name: str) -> bool:
        if self._allowed is not None and name not in self._allowed:
            return False
        return self._allow_writes or name not in WRITE_TOOLS

    async def run(self, goal: str, *, kind: str = "adhoc") -> AgentResult:
        started = utcnow()
        result = AgentResult("", "max_steps", 0, 0, 0, run_id=uuid.uuid4().hex)
        try:
            await self._loop(goal, result)
        except Exception as exc:
            await self._record(goal, kind, result, started, error=str(exc))
            raise
        await self._record(goal, kind, result, started)
        return result

    async def _record(
        self, goal: str, kind: str, result: AgentResult, started, *, error: str | None = None
    ) -> None:
        if self._runs is None:
            return
        run = AgentRun(
            run_id=result.run_id,
            kind=kind,
            goal=goal,
            backend=self._backend,
            model=self._llm.model,
            status="error" if error else result.stop_reason,
            answer=result.answer,
            error=error,
            steps=result.steps,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            started_at=started,
            finished_at=utcnow(),
            tool_trace=[asdict(t) for t in result.tool_trace],
        )
        try:
            await self._runs.save_run(run)
        except Exception as exc:  # noqa: BLE001 - a logging failure must not fail the run
            log.error("agent.run_log_failed", run_id=result.run_id, error=str(exc))

    async def _loop(self, goal: str, result: AgentResult) -> None:
        specs: list[ToolSpec] = [
            t for t in await self._tools.list_tools() if self._permitted(t.name)
        ]
        messages = [Message("user", goal)]
        retries_left = self._grounding_retries

        for step in range(1, self._max_steps + 1):
            response = await self._llm.complete(
                system=self._system,
                messages=messages,
                tools=specs,
                max_tokens=self._max_output_tokens,
            )
            result.steps = step
            result.input_tokens += response.input_tokens
            result.output_tokens += response.output_tokens

            if not response.tool_calls:
                result.answer = response.text
                result.stop_reason = "answered"
                result.grounding = check_grounding(
                    response.text, result.tool_outputs, number_sources=[goal]
                )
                if result.grounding.ok:
                    return
                log.warning(
                    "agent.ungrounded_answer",
                    numbers=result.grounding.ungrounded_numbers,
                    phrases=result.grounding.speculative_phrases,
                )
                if retries_left <= 0 or step == self._max_steps:
                    return
                retries_left -= 1
                messages.append(Message("assistant", response.text))
                messages.append(Message("user", result.grounding.feedback()))
                continue

            messages.append(Message("assistant", response.text, response.tool_calls))
            tool_results = [await self._execute(c, result) for c in response.tool_calls]
            messages.append(Message("user", tool_results=tuple(tool_results)))

            if result.input_tokens + result.output_tokens >= self._max_total_tokens:
                result.stop_reason = "token_budget"
                break

        result.answer = result.answer or "Stopped before reaching an answer (budget exhausted)."
        log.warning("agent.budget_exhausted", reason=result.stop_reason, steps=result.steps)

    async def _execute(self, call: ToolCall, result: AgentResult) -> ToolResult:
        if not self._permitted(call.name):
            text, is_error = f"tool '{call.name}' is not permitted for this run", True
        else:
            try:
                text, is_error = await self._tools.call(call.name, call.arguments)
            except Exception as exc:  # tool failures go back to the model, not up the stack
                text, is_error = f"tool '{call.name}' failed: {exc}", True
        if len(text) > self._max_tool_chars:
            text = text[: self._max_tool_chars] + "\n…[truncated]"
        result.tool_outputs.append(text)
        log.info("agent.tool_call", tool=call.name, error=is_error, chars=len(text))
        result.tool_trace.append(
            ToolTrace(call.name, call.arguments, is_error, len(text), text[:500])
        )
        return ToolResult(call.id, text, is_error)
