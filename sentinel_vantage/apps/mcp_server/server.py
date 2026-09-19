"""MCP server construction and tool registration.

Phase 0 exposes a single ``get_status`` tool. Its jobs: prove the server speaks the
current MCP protocol to a client, and force the output-envelope convention (every
result carries as_of / provider / feed / model_version / confidence) into place so
Phase 1 tools inherit it.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from sentinel_vantage import __version__
from sentinel_vantage.core.config import Settings, get_settings
from sentinel_vantage.core.envelope import make_envelope
from sentinel_vantage.core.health import check_health
from sentinel_vantage.core.versioning import NO_MODEL, SCHEMA_CONVENTIONS_VERSION


def build_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or get_settings()
    mcp = MCPServer(name="sentinel-vantage", version=__version__)

    @mcp.tool()
    async def get_status() -> dict[str, Any]:
        """Health and readiness of the Sentinel Vantage system.

        Returns dependency status (Postgres, Redis), environment, active data feed,
        and schema-conventions version. This is a status payload, not a scored
        result, so confidence is null.
        """
        health = await check_health(settings)
        envelope = make_envelope(
            data={
                "health": health.model_dump(),
                "schema_conventions_version": SCHEMA_CONVENTIONS_VERSION,
            },
            provider=settings.provider_name,
            feed=settings.feed_label,
            model_version=NO_MODEL,
            confidence=None,
        )
        return envelope.model_dump(mode="json")

    return mcp
