# Connecting a client to the Sentinel Vantage MCP server

This walks through wiring the server into the common desktop MCP clients: Claude Code,
Claude Desktop, VS Code (GitHub Copilot agent mode), Cursor, Windsurf, and generic
clients. The server speaks **streamable-HTTP**, so most clients connect by URL; a couple
of stdio-only clients use a small bridge.

## 0. Prerequisites

1. **Start the server.** It listens on streamable-HTTP at:

   ```
   http://localhost:8080/mcp
   ```

   Bring up the whole stack:

   ```bash
   cp .env.example .env    # set SV_POLYGON_API_KEY (+ SV_SEC_USER_AGENT for fundamentals)
   docker compose -f deploy/docker-compose.yml up --build
   ```

   or run just the server locally (Postgres + Redis must already be running):

   ```bash
   source .venv/bin/activate && sv-mcp
   ```

2. **Load data**, or every tool returns empty results:

   ```bash
   sv-migrate && sv-seed && sv-backfill      # trend data
   sv-fundamentals && sv-events              # research + catalysts (needs SV_SEC_USER_AGENT)
   ```

3. **Confirm it's up** — this should return HTTP 200:

   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/mcp \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
   ```

> **Security note:** there is **no authentication yet** (that's Phase 6). Keep the server
> bound to `localhost` or behind your own gateway/VPN. Do not expose `:8080` to the public
> internet. Provider secrets stay server-side in `.env` and are never returned by tools.

---

## Claude Code (CLI)

Add the server by URL (streamable-HTTP transport):

```bash
claude mcp add --transport http sentinel-vantage http://localhost:8080/mcp
```

Scope it if you like: `-s local` (default, this machine), `-s project` (writes
`.mcp.json`, shared with the repo), or `-s user` (all your projects). Then:

```bash
claude mcp list            # verify it's connected
claude mcp remove sentinel-vantage   # to undo
```

In a session, ask things like "what's trending today?" or "why did NVDA move?" — the
tools (`scan_trending_stocks`, `explain_move`, …) are invoked automatically.

---

## VS Code — GitHub Copilot (agent mode)

Requires Copilot Chat in **Agent** mode. Create a workspace file `.vscode/mcp.json`:

```json
{
  "servers": {
    "sentinel-vantage": {
      "type": "http",
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

Or add it globally via the Command Palette → **MCP: Add Server…** → **HTTP** → the URL
above. Open Copilot Chat, switch the mode selector to **Agent**, and confirm
Sentinel Vantage's tools appear in the tools picker. (For an always-available server
across every workspace, put the same `servers` block under the `mcp` key in your user
`settings.json`.)

---

## Cursor

Create `.cursor/mcp.json` in the project (or `~/.cursor/mcp.json` for all projects):

```json
{
  "mcpServers": {
    "sentinel-vantage": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

Then Cursor → **Settings → MCP** and check that the server shows as connected and its
tools are enabled.

---

## Claude Desktop

Claude Desktop's config is stdio-oriented, so bridge the HTTP server with `mcp-remote`
(requires Node.js/`npx`). Edit the config file:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "sentinel-vantage": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8080/mcp"]
    }
  }
}
```

Restart Claude Desktop; the tools appear under the tools (plug) icon. If your Claude
plan supports **Custom Connectors** (Settings → Connectors → Add custom connector), you
can instead paste the URL there directly, no bridge needed.

---

## Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "sentinel-vantage": {
      "serverUrl": "http://localhost:8080/mcp"
    }
  }
}
```

Then reload the MCP servers from Windsurf's Cascade / MCP settings panel.

---

## Any other MCP client

- **Native HTTP:** point the client at `http://localhost:8080/mcp` (transport type
  `http` / `streamable-http`). Config keys vary — usually `url` or `serverUrl` under an
  `mcpServers` / `servers` map.
- **stdio-only client:** wrap the URL with the bridge command
  `npx -y mcp-remote http://localhost:8080/mcp`.
- **Programmatic (Python):** use the MCP SDK's streamable-HTTP client against the same
  URL, then `list_tools()` / `call_tool(...)`.

---

## Verify the connection

Ask the client to call **`get_status`** — it should return Postgres/Redis health, the
active data feed, and the schema-conventions version. Then try:

| Ask | Tool |
|---|---|
| "What's trending today?" | `scan_trending_stocks` |
| "Why did NVDA move?" | `explain_move` |
| "Find GARP candidates" | `find_research_candidates` |
| "Compare AMD, NVDA, AVGO" | `compare_stocks` |
| "Give me a market brief" | `get_market_brief` |

## Troubleshooting

- **Tools don't appear / connection fails** — confirm the server is running and the curl
  check in step 0.3 returns `200`. Check the port matches `SV_MCP_PORT` (default 8080).
- **Tools return empty results** — the database has no data yet; run the data-load
  commands in step 0.2, and start `sv-worker` so scores are computed.
- **Client only supports stdio** — use the `mcp-remote` bridge shown above.
- **Alerts never fire** — they are evaluated by `sv-scheduler`, not the MCP request path;
  make sure that process is running.
