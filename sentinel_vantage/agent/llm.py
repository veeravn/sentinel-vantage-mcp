"""Provider-neutral LLM interface with two HTTP backends: the Anthropic Messages API and any
OpenAI-compatible ``/chat/completions`` endpoint (Ollama, llama-server, vLLM, LM Studio)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from sentinel_vantage.core.config import Settings

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMClient(Protocol):
    model: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> LLMResponse: ...

    async def aclose(self) -> None: ...


class _HttpClient:
    def __init__(self, http: httpx.AsyncClient | None, timeout: float) -> None:
        self._http = http or httpx.AsyncClient(timeout=timeout)

    async def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict:
        try:
            resp = await self._http.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"LLM returned HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    async def aclose(self) -> None:
        await self._http.aclose()


class AnthropicClient(_HttpClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        url: str = ANTHROPIC_URL,
        http: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(http, timeout)
        if not api_key:
            raise LLMError("SV_ANTHROPIC_API_KEY is required for the anthropic backend")
        self.model = model
        self._api_key = api_key
        self._url = url

    @staticmethod
    def _encode(messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            blocks: list[dict[str, Any]] = []
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in m.tool_calls
            ]
            blocks += [
                {
                    "type": "tool_result",
                    "tool_use_id": r.call_id,
                    "content": r.content,
                    "is_error": r.is_error,
                }
                for r in m.tool_results
            ]
            out.append({"role": m.role, "content": blocks})
        return out

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": self._encode(messages),
        }
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in tools
            ]
        headers = {"x-api-key": self._api_key, "anthropic-version": ANTHROPIC_VERSION}
        data = await self._post(self._url, headers, body)
        blocks = data.get("content", [])
        usage = data.get("usage", {})
        return LLMResponse(
            text="".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
            tool_calls=tuple(
                ToolCall(b["id"], b["name"], b.get("input") or {})
                for b in blocks
                if b.get("type") == "tool_use"
            ),
            stop_reason=data.get("stop_reason", ""),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            raw=data,
        )


class OpenAICompatClient(_HttpClient):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        http: httpx.AsyncClient | None = None,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(http, timeout)
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key

    @staticmethod
    def _encode(system: str, messages: list[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            for r in m.tool_results:
                out.append({"role": "tool", "tool_call_id": r.call_id, "content": r.content})
            if m.role == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.text or None}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                        }
                        for c in m.tool_calls
                    ]
                out.append(msg)
            elif m.text:
                out.append({"role": "user", "content": m.text})
        return out

    async def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": self._encode(system, messages),
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in tools
            ]
        headers = {"authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        data = await self._post(self._url, headers, body)
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"malformed LLM response: {str(data)[:500]}") from exc
        msg = choice.get("message", {})
        usage = data.get("usage", {})
        return LLMResponse(
            text=msg.get("content") or "",
            tool_calls=tuple(_parse_openai_call(c) for c in msg.get("tool_calls") or []),
            stop_reason=choice.get("finish_reason") or "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )


def _parse_openai_call(raw: dict[str, Any]) -> ToolCall:
    fn = raw.get("function", {})
    args = fn.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"_unparsed": args}
    return ToolCall(raw.get("id") or fn.get("name", ""), fn.get("name", ""), args)


def build_llm(settings: Settings, *, http: httpx.AsyncClient | None = None) -> LLMClient:
    if settings.llm_backend == "anthropic":
        return AnthropicClient(
            api_key=settings.anthropic_api_key, model=settings.llm_model, http=http
        )
    return OpenAICompatClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        http=http,
    )
