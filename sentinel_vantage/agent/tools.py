"""Tool access for the agent: a ``ToolSource`` protocol and an in-process adapter over the
MCP server so tools are defined once and shared with external MCP clients."""

from __future__ import annotations

from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer

from sentinel_vantage.agent.llm import ToolSpec

WRITE_TOOLS = frozenset({"create_watchlist", "create_alert_rule"})


class ToolSource(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Return ``(text, is_error)``."""
        ...


class MCPToolSource:
    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(t.name, t.description or "", t.input_schema)
            for t in await self._server.list_tools()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = await self._server.call_tool(name, arguments)
        text = "\n".join(c.text for c in getattr(result, "content", []) or [] if hasattr(c, "text"))
        return text, bool(getattr(result, "is_error", False))
