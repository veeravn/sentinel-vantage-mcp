# Sentinel Vantage MCP

A market-intelligence [MCP](https://modelcontextprotocol.io) server for the US equity
market. It continuously ingests market data, computes **deterministic** trend and
strategy-research scores with reason codes and provenance, and exposes them to an AI
assistant through typed MCP tools. Scores are computed by the engine; the LLM explains
and investigates them — it never invents weights.

Two independent outputs:

- **Trend Score (0–100)** — how strongly a stock is attracting price/volume/attention.
- **Research Candidate Score (0–100)** — how attractive it is for research under an
  explicit strategy (Growth, GARP, Quality, Value, Momentum), after gates and penalties.

The MCP layer is a **query interface** downstream of an always-on monitoring engine —
monitoring runs whether or not a client is connected. v1 is **research-only**: there is
no order-placement tool.

Delivery status and the phase-by-phase roadmap live in [ROADMAP.md](ROADMAP.md).

## Architecture

Three independent processes (design section 28):

| Process | Package | Role |
|---|---|---|
| MCP server | `apps/mcp_server` | Query/reasoning interface. Thin layer over domain services. |
| Market worker | `apps/market_worker` | Always-on ingestion → features → scoring. |
| Scheduler | `apps/scheduler` | Alert-rule evaluation and briefings, outside the MCP request path. |

Supporting layers: `providers/` (swappable data adapters), `storage/` (Postgres +
Redis), `domain/` (business logic), `core/` (config, versioning, provenance, health).

```
sentinel_vantage/
  core/        config, versioning, envelope (provenance), time, logging, health
  providers/   market_data/ fundamentals/ news/  (swappable adapters)
  storage/     postgres, redis
  domain/      market/ features/ trend/ research/ catalysts/ alerts/
  apps/        mcp_server/ market_worker/ scheduler/
  backtest/    point-in-time backtesting
strategies/    version-controlled strategy configs
deploy/        Dockerfile, docker-compose.yml, postgres init
docs/          ADRs and design notes
tests/
```

## Data feed

Polygon.io. Every tier has 100% consolidated market coverage, so the trend features are
honest even on the free tier. Develop on **Basic ($0)**; run the MVP on **Starter
($29/mo)** for unlimited calls, WebSockets, Flat Files backfill, and 5y history. Feed
provenance (`polygon/delayed` vs `polygon/realtime`) is stamped on every bar and score.
Fundamentals and filings come from SEC EDGAR (no key; set `SV_SEC_USER_AGENT`).

## Usage

Run the full stack (Postgres + Timescale, Redis, and the three processes). A one-shot
`migrate` service creates the schema and seeds the universe automatically before the app
services start:

```bash
cp .env.example .env          # set SV_POLYGON_API_KEY (and SV_SEC_USER_AGENT for fundamentals)
docker compose -f deploy/docker-compose.yml up --build
```

The MCP server listens on `http://localhost:8080/mcp` (streamable-http). Call the
`get_status` tool to verify Postgres/Redis health, the active feed, and schema version.
To wire it into a client (Claude Code, Claude Desktop, VS Code Copilot, Cursor,
Windsurf), see [docs/CONNECTING.md](docs/CONNECTING.md).

### Load data

Schema + universe are created automatically on `up`. Market/fundamental/event **data**
is not (free-tier backfill is slow). Load it once with the `bootstrap` profile:

```bash
docker compose -f deploy/docker-compose.yml --profile bootstrap up
```

That runs `sv-backfill`, `sv-fundamentals`, and `sv-events` once (best-effort;
fundamentals/events need `SV_SEC_USER_AGENT`). Or run them by hand, in Docker or locally:

```bash
sv-backfill             # daily bars from Polygon (free tier: self-throttles)
sv-fundamentals         # point-in-time SEC XBRL fundamentals (needs SV_SEC_USER_AGENT)
sv-events               # SEC filings as catalyst events
```

### Command-line tools

| Command | Purpose |
|---|---|
| `sv-mcp` | Run the MCP server (streamable-http). |
| `sv-worker` | Always-on worker: score the latest session, publish the rank cache. |
| `sv-scheduler` | Evaluate alert rules and briefings on a cadence. |
| `sv-migrate` / `sv-seed` | Apply migrations / seed the reference universe. |
| `sv-backfill` / `sv-fundamentals` / `sv-events` | Load bars / fundamentals / filing events. |
| `sv-backtest` | Point-in-time backtest (`sv-backtest trend`, `sv-backtest garp --horizon 60`). |

### MCP tools

`get_status`, `scan_trending_stocks`, `analyze_stock`, `get_score_history`,
`find_research_candidates`, `compare_stocks`, `explain_move`, `create_watchlist`,
`create_alert_rule`, `list_alert_events`, `get_watchlist_changes`, `get_market_brief`.

### Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check . && ruff format --check .
pytest -q                      # unit tests run without a live database
SV_RUN_DB_TESTS=1 pytest -q     # also run the Postgres/Redis integration tests
```

## License

Proprietary — all rights reserved. Not licensed for redistribution or use without the
copyright holder's permission.
