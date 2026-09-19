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

## Status

**Phase 1 — Trend MVP (in progress).** The deterministic trend engine is built and
tested end to end: feature engine → eligibility gates → `trend-v0` cross-sectional
scoring with reason codes, risk flags, and confidence, exposed through the
`scan_trending_stocks`, `analyze_stock`, and `get_score_history` MCP tools. A replay
test proves determinism. The Polygon market-data adapter and the persistence layer
(Timescale schema + migrations, Postgres/Redis repositories, universe seed) are built
and verified against real Timescale + Redis in CI. **Next:** worker wiring — backfill
via Polygon, then ingest → features → score on a cadence, writing snapshots.

Bring up the stack and initialize the database:

```bash
cp .env.example .env   # set SV_POLYGON_API_KEY
docker compose -f deploy/docker-compose.yml up -d postgres redis
sv-migrate && sv-seed  # create schema (hypertables) + seed the universe
```

Phase 0 (done): skeleton, Docker stack, three processes, provider interfaces, output
conventions, `get_status`. See [ADR-0001](docs/adr-0001-phase0-conventions.md).

## Architecture

Three independent processes (design section 28):

| Process | Package | Role |
|---|---|---|
| MCP server | `apps/mcp_server` | Query/reasoning interface. Thin layer over domain services. |
| Market worker | `apps/market_worker` | Always-on ingestion → features → scoring. |
| Scheduler | `apps/scheduler` | Alert-rule evaluation and briefings, outside the MCP request path. |

Supporting layers: `providers/` (swappable data adapters), `storage/` (Postgres +
Redis), `domain/` (business logic), `core/` (config, versioning, provenance, health).

## Data feed

Polygon.io. Every tier has 100% consolidated market coverage, so the trend features are
honest even on the free tier. Develop on **Basic ($0)**; run the MVP on **Starter
($29/mo)** for unlimited calls, WebSockets, Flat Files backfill, and 5y history. Feed
provenance (`polygon/delayed` vs `polygon/realtime`) is stamped on every bar and score.

## Quickstart

```bash
cp .env.example .env          # then set SV_POLYGON_API_KEY

# Run the full stack (Postgres + Timescale, Redis, and the three processes)
docker compose -f deploy/docker-compose.yml up --build
```

The MCP server listens on `http://localhost:8080` (streamable-http). Call the
`get_status` tool to verify Postgres/Redis health, the active feed, and schema version.

### Local development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check . && ruff format --check .
pytest -q
```

> The tests run without a live database — health pings degrade to `down` gracefully.

## Layout

```
sentinel_vantage/
  core/        config, versioning, envelope (provenance), time, logging, health
  providers/   market_data/ fundamentals/ news/  (swappable adapters)
  storage/     postgres, redis
  domain/      market/ features/ trend/ research/ catalysts/ alerts/
  apps/        mcp_server/ market_worker/ scheduler/
strategies/    version-controlled strategy configs (Phase 2)
backtest/      point-in-time backtesting (Phase 4)
deploy/        Dockerfile, docker-compose.yml, postgres init
docs/          ADRs and design notes
tests/
```

## Roadmap

Phase 0 Skeleton · Phase 1 Trend MVP · Phase 2 Fundamentals + first strategy (GARP) ·
Phase 3 Catalysts · Phase 4 Backtesting · Phase 5 Watchlists/Alerts · Phase 6 Hardening.
