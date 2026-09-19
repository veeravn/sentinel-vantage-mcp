"""Market worker process — the always-on monitoring path.

Ingests bars, updates rolling features, and recomputes scores on a cadence,
independent of whether any MCP client is connected. Phase 0 is a lifecycle stub;
Phase 1 fills in ingestion -> features -> trend scoring.
"""
