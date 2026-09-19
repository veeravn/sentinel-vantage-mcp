"""The MCP server registers the status tool and returns a provenance envelope."""

from __future__ import annotations

import json

from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings


async def test_status_tool_is_registered():
    server = build_server(Settings())
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "get_status" in names


async def test_status_tool_returns_envelope_shape():
    settings = Settings(
        postgres_dsn="postgresql://nope:nope@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    )
    server = build_server(settings)
    result = await server.call_tool("get_status", {})

    assert not result.is_error
    payload = json.loads(result.content[0].text)
    assert payload["provenance"]["feed"] == settings.feed_label
    assert payload["provenance"]["confidence"] is None
    assert payload["provenance"]["model_version"] == "n/a"
    assert "health" in payload["data"]
