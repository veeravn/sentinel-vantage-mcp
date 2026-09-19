"""Sentinel Vantage — market-intelligence MCP server.

Package layout mirrors the system design document:

- ``core``      shared conventions: config, versioning, provenance envelope, time, health.
- ``providers`` swappable data-source adapters (market data, fundamentals, news).
- ``storage``   Postgres (durable) and Redis (latest/rank cache) access.
- ``domain``    business logic services (features, trend, research, catalysts, alerts).
- ``apps``      the three independent processes: mcp_server, market_worker, scheduler.

Phase 0 establishes this skeleton and the cross-cutting conventions. Later phases
fill in the domain services without changing the shape.
"""

__version__ = "0.1.0"
