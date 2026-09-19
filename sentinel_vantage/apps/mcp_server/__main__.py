"""Entrypoint: run the MCP server over the streamable-http transport."""

from __future__ import annotations

from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    log = get_logger("mcp_server")
    log.info(
        "mcp_server.starting",
        host=settings.mcp_host,
        port=settings.mcp_port,
        feed=settings.feed_label,
    )
    server = build_server(settings)
    # Stateless streamable-http transport (current MCP protocol generation).
    server.run(
        transport="streamable-http",
        host=settings.mcp_host,
        port=settings.mcp_port,
        stateless_http=True,
    )


if __name__ == "__main__":
    main()
