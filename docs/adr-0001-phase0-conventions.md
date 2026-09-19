# ADR-0001: Phase 0 conventions

Status: Accepted — 2026-09-18

These are the cross-cutting conventions established in Phase 0. Later phases inherit
them rather than re-litigating them.

## 1. Three independent processes

`mcp_server`, `market_worker`, and `scheduler` are separate entrypoints and separate
containers. Monitoring, scoring, and alerting must run with **no MCP client
connected** (design section 28). Starting as a monolith would couple the query path to
the data path; we refuse that coupling up front.

## 2. Provenance on every output

Every value that leaves a service or tool is wrapped in an `Envelope` carrying
`as_of`, `provider`, `feed`, `model_version`, and `confidence`
(`core/envelope.py`). A missing/partial input must lower `confidence` — never be
silently dropped into a normal-confidence result.

## 3. Versioning is deliberate and additive

`core/versioning.py` holds the model/feature/schema versions. Bumping a version
creates a new interpretation; it never mutates the meaning of historical rows. This is
what keeps scores reproducible and backtestable.

## 4. UTC everywhere; calendar kept separate

All stored timestamps are UTC (`core/timeutils.py`). Exchange-session semantics live in
the market-calendar provider, not baked into timestamps.

## 5. Secrets are server-side only

Provider API keys load via `SV_`-prefixed env into `core/config.py` and are never
returned through MCP tools.

## 6. Providers are swappable

Data sources sit behind the ABCs in `providers/base.py`. The scoring engine depends on
the normalized `Bar`/`Quote`/`Session` schemas, not on any vendor SDK.

## 7. Degrade, don't crash

A dependency or provider outage degrades the affected component (health = `down`/`degraded`)
without taking down the process. Health checks never raise.
