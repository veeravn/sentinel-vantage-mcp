"""Bearer-token auth for the MCP endpoint: a pure-ASGI middleware (not BaseHTTPMiddleware,
so it never buffers the SSE response) that 401s a missing/wrong token, compared in
constant time. Opt-in — not installed when no token is configured."""

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
