"""Bearer-token ASGI middleware: rejects bad tokens, passes valid + non-MCP traffic."""

from __future__ import annotations

from sentinel_vantage.apps.mcp_server.auth import BearerAuthMiddleware


class _Downstream:
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send) -> None:
        self.called = True


async def _run(mw, path="/mcp", scope_type="http", auth: str | None = None):
    scope = {"type": scope_type, "path": path, "headers": []}
    if auth is not None:
        scope["headers"] = [(b"authorization", auth.encode())]
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        sent.append(msg)

    await mw(scope, receive, send)
    return sent


async def test_rejects_missing_token():
    down = _Downstream()
    sent = await _run(BearerAuthMiddleware(down, token="s3cret"))
    assert not down.called
    assert sent[0]["status"] == 401
    assert any(h[0] == b"www-authenticate" for h in sent[0]["headers"])


async def test_rejects_wrong_token():
    down = _Downstream()
    sent = await _run(BearerAuthMiddleware(down, token="s3cret"), auth="Bearer nope")
    assert not down.called
    assert sent[0]["status"] == 401


async def test_accepts_correct_token():
    down = _Downstream()
    await _run(BearerAuthMiddleware(down, token="s3cret"), auth="Bearer s3cret")
    assert down.called


async def test_non_mcp_path_is_not_protected():
    down = _Downstream()
    await _run(BearerAuthMiddleware(down, token="s3cret"), path="/healthz")
    assert down.called


async def test_lifespan_passes_through():
    down = _Downstream()
    await _run(BearerAuthMiddleware(down, token="s3cret"), scope_type="lifespan", path="")
    assert down.called
