"""Bearer-token auth for the MCP HTTP endpoint (Phase 6).

A pure-ASGI middleware: it inspects the ``Authorization`` header on requests to the MCP
path and returns 401 when the token is missing or wrong, otherwise passes the request
through untouched. Implemented at the ASGI layer (not Starlette's BaseHTTPMiddleware) so
it never wraps or buffers the streamable-HTTP / SSE response body.

The token is compared in constant time. Auth is opt-in: with no token configured the
middleware is not installed, so local development stays keyless.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp, *, token: str, protected_prefix: str = "/mcp") -> None:
        self._app = app
        self._expected = f"Bearer {token}"
        self._prefix = protected_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and scope.get("path", "").startswith(self._prefix):
            headers = dict(scope.get("headers") or [])
            presented = headers.get(b"authorization", b"").decode("latin-1")
            if not (presented and hmac.compare_digest(presented, self._expected)):
                await self._unauthorized(send)
                return
        await self._app(scope, receive, send)

    async def _unauthorized(self, send: Send) -> None:
        body = b'{"error":"unauthorized"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="sentinel-vantage"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
