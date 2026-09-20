# Roadmap & status

Delivery status by phase. Phases 0–5 are complete; Phase 6 (hardening) remains.

| Phase | Scope | Status |
|---|---|---|
| 0 | Skeleton | ✅ Done |
| 1 | Trend MVP | ✅ Done |
| 2 | Fundamentals + first strategy (GARP) | ✅ Done |
| 3 | Catalysts | ✅ Done |
| 4 | Backtesting | ✅ Done |
| 5 | Watchlists & Alerts | ✅ Done |
| 6 | Hardening | ⬜ Not started |

## Phase 0 — Skeleton ✅

Repo, Docker stack (Postgres/Timescale + Redis), three independent processes, provider
interfaces, and the cross-cutting conventions (provenance envelope, versioning, UTC,
health). One `get_status` MCP tool. See [ADR-0001](docs/adr-0001-phase0-conventions.md).

## Phase 1 — Trend MVP ✅

Deterministic trend engine: feature engine → eligibility gates → `trend-v0`
cross-sectional scoring with reason codes, risk flags, and confidence. A replay test
proves determinism. Polygon market-data adapter (with 429 backoff **and** a proactive
rolling-window rate limiter). Persistence: Timescale schema + migrations,
Postgres/Redis repositories, universe seed. The market worker scores the latest session
on a cadence, persists feature + score snapshots, and publishes the Redis rank cache.
MCP tools read that same state — `scan_trending_stocks` serves the warm Redis cache and
falls back to an on-demand Postgres recompute. Verified end to end on live Polygon data,
including the MCP server over HTTP.

Tools: `scan_trending_stocks`, `analyze_stock`, `get_score_history`.

## Phase 2 — Fundamentals + GARP ✅

SEC EDGAR adapter (point-in-time XBRL facts, append-only by `filed_at`), fundamentals
storage + normalization (revenue/EPS growth, margins, ROE, leverage, P/E, EV/Sales with
tag-priority fallback), and the `research-v1` GARP engine (hard gates → cross-sectional
factor scoring → risk penalties → confidence). Strategies are version-controlled YAML.
Verified live on real Polygon prices + real SEC data (AAPL correctly excluded on GARP's
growth gate).

Tools: `find_research_candidates`, `compare_stocks`. CLI: `sv-fundamentals`.

## Phase 3 — Catalysts ✅

SEC filings as structured events (10-K/10-Q/8-K, no key), a catalyst correlator that
scores temporal proximity, relevance, and novelty into weak/moderate/strong evidence,
and `explain_move` — it finds a symbol's largest recent move and attaches ranked
catalyst evidence with a causal-confidence label, never a proven cause. Verified live:
NVDA's move traced to same-day 8-K/10-Q (strong); a move with no nearby filing correctly
returns no catalyst.

Tool: `explain_move`. CLI: `sv-events`.

## Phase 4 — Backtesting ✅

Point-in-time backtest engine ([backtest/](sentinel_vantage/backtest)) that replays a
model over a rebalance schedule using only data available at each `as_of`, reporting
forward-return-by-score-bucket, rank IC, top-minus-bottom spread, hit rate, turnover, and
coverage. Works for both the trend and research models. Meaningful evaluation needs a
broad, multi-sector universe (a full backfill).

CLI: `sv-backtest trend` / `sv-backtest garp --horizon 60`.

## Phase 5 — Watchlists & Alerts ✅

A structured rule DSL (validated, not LLM text), an alert engine with per-(rule,symbol)
cooldown dedup that persists evaluated values for audit, watchlist diffs, and scheduled
briefings — all evaluated by the always-on `scheduler` process independent of any MCP
client. Rules read like `["trend_score >= 85", "volume_ratio >= 2.0"]`.

Tools: `create_watchlist`, `create_alert_rule`, `list_alert_events`,
`get_watchlist_changes`, `get_market_brief`.

## Phase 6 — Hardening 🚧

In progress:

- ✅ **Bearer-token auth** on the MCP endpoint (`SV_MCP_AUTH_TOKEN`) — a pure-ASGI
  middleware that 401s missing/wrong tokens without touching the streaming response.
  Opt-in: keyless when unset (local dev). Reverse-proxy config in
  [deploy/Caddyfile](deploy/Caddyfile).
- ⬜ Per-client quotas / rate limits.
- ⬜ Multi-provider failover.
- ⬜ Full observability and metrics.
- ⬜ Chaos / scale tests.
- ⬜ Secrets in a secret manager; least-privilege DB roles.

## Backlog / quick wins

- ✅ Additional strategy profiles — Growth, Quality, Value, and Momentum ship as
  version-controlled YAML in [sentinel_vantage/strategies/](sentinel_vantage/strategies),
  auto-discovered by the loader
  and reweighting the same five factors as GARP (`find_research_candidates` /
  `compare_stocks` accept them by id or name).
- Research worker cycle: persist `strategy_score` on a cadence + a Redis cache.
- Notification delivery for alerts (email / Slack / push).
- ✅ XBRL tag-coverage refinement — expanded us-gaap candidate lists (ASC 606 revenue
  variants, combined basic/diluted EPS, NCI-inclusive equity, capital-lease debt); the
  SEC adapter now also reads the `dei` taxonomy so `EntityCommonStockSharesOutstanding`
  backs up the frequently-absent us-gaap share count; and gross profit is derived from
  revenue − cost of revenue (period-aligned) when `GrossProfit` isn't tagged.
- Full-universe backfill so the backtest has real breadth (fast on a paid Polygon tier).
- Granular trend confidence: factor in bar freshness and per-feature quality so it varies
  meaningfully instead of saturating at 1.0 for full-history large caps (today it's a
  coarse completeness × history × benchmark product; it is data-quality, not a calibrated
  probability).
- Scheduled daily backfill so the scored "as of" tracks the latest session automatically
  (today `as_of` only advances when `sv-backfill` is re-run; no live minute-stream ingest).
