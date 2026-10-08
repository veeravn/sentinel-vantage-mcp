"""Agent loop and both LLM backends, with scripted LLMs and mocked HTTP."""

from __future__ import annotations

import json

import httpx
import pytest

from sentinel_vantage.agent.llm import (
    AnthropicClient,
    LLMError,
    LLMResponse,
    Message,
    OpenAICompatClient,
    ToolCall,
    ToolResult,
    ToolSpec,
    build_llm,
)
from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.core.config import Settings

SPEC = ToolSpec("get_status", "status", {"type": "object", "properties": {}})
WRITE_SPEC = ToolSpec("create_watchlist", "write", {"type": "object", "properties": {}})


class FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return [SPEC, WRITE_SPEC]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return json.dumps({"ok": True}), False


class ScriptedLLM:
    model = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.seen_tools: list[list[str]] = []
        self.seen_messages: list[list[Message]] = []

    async def complete(self, *, system, messages, tools, max_tokens):
        self.seen_tools.append([t.name for t in tools])
        self.seen_messages.append(list(messages))
        return self._responses.pop(0)

    async def aclose(self) -> None:
        pass


def _call(name="get_status", id="c1", **args):
    return LLMResponse("", (ToolCall(id, name, args),), input_tokens=10, output_tokens=5)


async def test_loop_calls_tool_then_answers():
    tools = FakeTools()
    llm = ScriptedLLM([_call(), LLMResponse("done", input_tokens=20, output_tokens=5)])
    result = await AgentRunner(llm, tools).run("status?")
    assert result.answer == "done"
    assert result.stop_reason == "answered"
    assert result.steps == 2
    assert (result.input_tokens, result.output_tokens) == (30, 10)
    assert tools.calls == [("get_status", {})]
    assert [t.name for t in result.tool_trace] == ["get_status"]
    fed_back = llm.seen_messages[1][-1].tool_results[0]
    assert fed_back.call_id == "c1" and "ok" in fed_back.content


async def test_writes_hidden_and_blocked_by_default():
    tools = FakeTools()
    llm = ScriptedLLM([_call("create_watchlist"), LLMResponse("ok")])
    result = await AgentRunner(llm, tools).run("make a list")
    assert llm.seen_tools[0] == ["get_status"]
    assert tools.calls == []
    assert result.tool_trace[0].is_error


async def test_writes_allowed_when_enabled():
    tools = FakeTools()
    llm = ScriptedLLM([_call("create_watchlist"), LLMResponse("ok")])
    await AgentRunner(llm, tools, allow_writes=True).run("make a list")
    assert llm.seen_tools[0] == ["get_status", "create_watchlist"]
    assert tools.calls == [("create_watchlist", {})]


async def test_max_steps_budget():
    llm = ScriptedLLM([_call(id=f"c{i}") for i in range(3)])
    result = await AgentRunner(llm, FakeTools(), max_steps=3).run("loop")
    assert result.stop_reason == "max_steps"
    assert result.steps == 3
    assert "budget" in result.answer


async def test_token_budget():
    llm = ScriptedLLM([_call(), LLMResponse("never")])
    result = await AgentRunner(llm, FakeTools(), max_total_tokens=10).run("x")
    assert result.stop_reason == "token_budget"


async def test_tool_exception_returned_to_model():
    class Boom(FakeTools):
        async def call(self, name, arguments):
            raise RuntimeError("db down")

    llm = ScriptedLLM([_call(), LLMResponse("sorry")])
    result = await AgentRunner(llm, Boom()).run("x")
    assert result.answer == "sorry"
    assert result.tool_trace[0].is_error
    assert "db down" in llm.seen_messages[1][-1].tool_results[0].content


def _mock(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_anthropic_round_trip():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "checking"},
                    {"type": "tool_use", "id": "tu1", "name": "get_status", "input": {}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    client = AnthropicClient(api_key="k", model="m", http=_mock(handler))
    history = [
        Message("user", "hi"),
        Message("assistant", "", (ToolCall("a", "get_status", {}),)),
        Message("user", tool_results=(ToolResult("a", "{}"),)),
    ]
    resp = await client.complete(system="sys", messages=history, tools=[SPEC], max_tokens=50)
    assert captured["headers"]["x-api-key"] == "k"
    body = captured["body"]
    assert body["system"] == "sys" and body["tools"][0]["input_schema"] == SPEC.input_schema
    assert body["messages"][1]["content"][0]["type"] == "tool_use"
    assert body["messages"][2]["content"][0]["type"] == "tool_result"
    assert resp.text == "checking"
    assert resp.tool_calls == (ToolCall("tu1", "get_status", {}),)
    assert (resp.input_tokens, resp.output_tokens) == (7, 3)


async def test_openai_compat_round_trip():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "t1",
                                    "type": "function",
                                    "function": {"name": "get_status", "arguments": "{}"},
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    client = OpenAICompatClient(base_url="http://x/v1/", model="m", http=_mock(handler))
    history = [
        Message("user", "hi"),
        Message("assistant", "", (ToolCall("a", "get_status", {}),)),
        Message("user", tool_results=(ToolResult("a", "{}"),)),
    ]
    resp = await client.complete(system="sys", messages=history, tools=[SPEC], max_tokens=50)
    assert captured["url"] == "http://x/v1/chat/completions"
    roles = [m["role"] for m in captured["body"]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert captured["body"]["tools"][0]["function"]["name"] == "get_status"
    assert resp.tool_calls == (ToolCall("t1", "get_status", {}),)
    assert resp.text == "" and resp.input_tokens == 4


async def test_http_error_raises_llm_error():
    client = AnthropicClient(
        api_key="k", model="m", http=_mock(lambda r: httpx.Response(401, text="bad key"))
    )
    with pytest.raises(LLMError, match="401"):
        await client.complete(system="s", messages=[Message("user", "x")], tools=[], max_tokens=5)


def test_build_llm_selects_backend():
    assert isinstance(
        build_llm(Settings(llm_backend="anthropic", anthropic_api_key="k")), AnthropicClient
    )
    assert isinstance(build_llm(Settings(llm_backend="openai_compat")), OpenAICompatClient)
    with pytest.raises(LLMError):
        build_llm(Settings(llm_backend="anthropic", anthropic_api_key=""))


async def test_mcp_tool_source_lists_and_calls():
    from conftest import make_daily_bars

    from sentinel_vantage.agent.tools import MCPToolSource
    from sentinel_vantage.apps.mcp_server.server import build_server
    from sentinel_vantage.domain.trend.service import TrendService
    from sentinel_vantage.storage.memory import InMemoryBarRepository

    bars = InMemoryBarRepository({"SPY": make_daily_bars("SPY", [100.0] * 70, [1e6] * 70)})
    source = MCPToolSource(build_server(Settings(), trend=TrendService(bars)))
    names = {t.name for t in await source.list_tools()}
    assert {"get_status", "analyze_stock"} <= names
    text, is_error = await source.call("get_status", {})
    assert not is_error and json.loads(text)


async def test_run_is_logged_with_trace():
    from sentinel_vantage.storage.memory import InMemoryAgentRunRepository

    runs = InMemoryAgentRunRepository()
    llm = ScriptedLLM([_call(), LLMResponse("done", input_tokens=2, output_tokens=1)])
    result = await AgentRunner(llm, FakeTools(), runs=runs, backend="fake").run("q", kind="adhoc")
    [row] = await runs.list_runs()
    assert row.run_id == result.run_id
    assert (row.kind, row.status, row.answer, row.backend, row.model) == (
        "adhoc",
        "answered",
        "done",
        "fake",
        "fake",
    )
    assert row.steps == 2 and row.tool_trace[0]["name"] == "get_status"
    assert "ok" in row.tool_trace[0]["output_preview"]


async def test_failed_run_is_logged_and_reraised():
    from sentinel_vantage.storage.memory import InMemoryAgentRunRepository

    class FailingLLM(ScriptedLLM):
        async def complete(self, **kwargs):
            raise LLMError("boom")

    runs = InMemoryAgentRunRepository()
    with pytest.raises(LLMError):
        await AgentRunner(FailingLLM([]), FakeTools(), runs=runs).run("q")
    [row] = await runs.list_runs()
    assert row.status == "error" and row.error == "boom"


async def test_run_log_failure_does_not_fail_run():
    class BrokenRepo:
        async def save_run(self, run):
            raise RuntimeError("db down")

    llm = ScriptedLLM([LLMResponse("fine")])
    result = await AgentRunner(llm, FakeTools(), runs=BrokenRepo()).run("q")
    assert result.answer == "fine"


class _Notifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, subject, body):
        self.sent.append((subject, body))


async def test_daily_brief_delivers_and_logs():
    from sentinel_vantage.agent.brief import BRIEF_KIND, BRIEF_SUBJECT, run_daily_brief
    from sentinel_vantage.storage.memory import InMemoryAgentRunRepository

    runs, notifier = InMemoryAgentRunRepository(), _Notifier()
    llm = ScriptedLLM([_call(), LLMResponse("Market summary: no notable moves.")])
    runner = AgentRunner(llm, FakeTools(), runs=runs)
    await run_daily_brief(runner, notifier)
    assert notifier.sent == [(BRIEF_SUBJECT, "Market summary: no notable moves.")]
    assert (await runs.list_runs(kind=BRIEF_KIND))[0].status == "answered"


async def test_daily_brief_not_delivered_when_incomplete():
    from sentinel_vantage.agent.brief import run_daily_brief

    notifier = _Notifier()
    llm = ScriptedLLM([_call(id=f"c{i}") for i in range(2)])
    result = await run_daily_brief(AgentRunner(llm, FakeTools(), max_steps=2), notifier)
    assert result.stop_reason == "max_steps"
    assert notifier.sent == []


async def test_brief_job_is_read_only_allowlist():
    from sentinel_vantage.agent.brief import BRIEF_TOOLS
    from sentinel_vantage.agent.tools import WRITE_TOOLS

    assert not BRIEF_TOOLS & WRITE_TOOLS


def test_brief_goal_forbids_sector_themes_and_markdown():
    from sentinel_vantage.agent.brief import BRIEF_GOAL

    assert "sector" in BRIEF_GOAL and "plain text" in BRIEF_GOAL.lower()


def test_to_plain_text_strips_markdown():
    from sentinel_vantage.agent.brief import to_plain_text

    md = "---\n\n## **Daily brief**\n\n- **TSLA** (89.8)\n\n\n\n---\n__note__"
    assert to_plain_text(md) == "Daily brief\n\n- TSLA (89.8)\n\nnote"


async def test_daily_brief_sends_plain_text():
    from sentinel_vantage.agent.brief import run_daily_brief

    notifier = _Notifier()
    llm = ScriptedLLM([LLMResponse("## **Daily brief**\n- all quiet")])
    await run_daily_brief(AgentRunner(llm, FakeTools()), notifier)
    assert notifier.sent[0][1] == "Daily brief\n- all quiet"


def test_brief_and_investigation_can_check_data_freshness():
    from sentinel_vantage.agent.alert_investigator import INVESTIGATION_TOOLS
    from sentinel_vantage.agent.brief import BRIEF_GOAL, BRIEF_TOOLS

    assert "get_status" in BRIEF_TOOLS and "get_status" in INVESTIGATION_TOOLS
    assert "data_freshness.stale" in BRIEF_GOAL
