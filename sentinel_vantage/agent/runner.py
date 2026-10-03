"""The agent loop: call the model, execute requested tools, feed results back, and repeat
until the model answers or a budget (steps, tokens) is exhausted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sentinel_vantage.agent.llm import LLMClient, Message, ToolCall, ToolResult, ToolSpec
from sentinel_vantage.agent.prompts import SYSTEM_PROMPT
from sentinel_vantage.agent.tools import WRITE_TOOLS, ToolSource
from sentinel_vantage.core.logging import get_logger

log = get_logger("agent")

StopReason = Literal["answered", "max_steps", "token_budget"]


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    is_error: bool
    output_chars: int


@dataclass
class AgentResult:
    answer: str
    stop_reason: StopReason
    steps: int
    input_tokens: int
    output_tokens: int
    tool_trace: list[ToolTrace] = field(default_factory=list)


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

    def _permitted(self, name: str) -> bool:
        if self._allowed is not None and name not in self._allowed:
            return False
        return self._allow_writes or name not in WRITE_TOOLS

    async def run(self, goal: str) -> AgentResult:
        specs: list[ToolSpec] = [
            t for t in await self._tools.list_tools() if self._permitted(t.name)
        ]
        messages = [Message("user", goal)]
        result = AgentResult("", "max_steps", 0, 0, 0)

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
                return result

            messages.append(Message("assistant", response.text, response.tool_calls))
            tool_results = [await self._execute(c, result) for c in response.tool_calls]
            messages.append(Message("user", tool_results=tuple(tool_results)))

            if result.input_tokens + result.output_tokens >= self._max_total_tokens:
                result.stop_reason = "token_budget"
                break

        result.answer = result.answer or "Stopped before reaching an answer (budget exhausted)."
        log.warning("agent.budget_exhausted", reason=result.stop_reason, steps=result.steps)
        return result

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
        log.info("agent.tool_call", tool=call.name, error=is_error, chars=len(text))
        result.tool_trace.append(ToolTrace(call.name, call.arguments, is_error, len(text)))
        return ToolResult(call.id, text, is_error)
