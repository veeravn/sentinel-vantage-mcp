"""Run the MCP server over streamable-http: build the Starlette app, wrap it with
bearer-token auth when SV_MCP_AUTH_TOKEN is set, and serve it with uvicorn."""

from __future__ import annotations

import uvicorn

from sentinel_vantage.apps.mcp_server.auth import BearerAuthMiddleware
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging, get_logger

MCP_PATH = "/mcp"


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    log = get_logger("mcp_server")

    server = build_server(settings)
    # Stateless streamable-http transport (current MCP protocol generation).
    app = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        host=settings.mcp_host,
    )

    if settings.mcp_auth_token:
        app = BearerAuthMiddleware(app, token=settings.mcp_auth_token, protected_prefix=MCP_PATH)
        log.info("mcp_server.auth_enabled")
    else:
        log.warning(
            "mcp_server.auth_disabled",
            hint="set SV_MCP_AUTH_TOKEN to require a bearer token before exposing on a network",
        )

    log.info(
        "mcp_server.starting",
        host=settings.mcp_host,
        port=settings.mcp_port,
        feed=settings.feed_label,
    )
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")


if __name__ == "__main__":
    main()
