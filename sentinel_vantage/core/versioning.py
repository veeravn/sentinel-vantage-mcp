"""Model and schema versions.

Every persisted score and feature snapshot records the version that produced it, so
outputs stay reproducible and backtestable. Bumping a version is a deliberate act: it
creates a *new* interpretation rather than mutating the meaning of historical rows.
Never reuse a version string after its scoring logic or weights have changed.
"""

from __future__ import annotations

# Scoring models (Phase 1 ships trend-v0; research/catalyst arrive in later phases).
TREND_MODEL_VERSION = "trend-v0"
RESEARCH_MODEL_VERSION = "research-v0"
CATALYST_MODEL_VERSION = "catalyst-v0"

# Feature set that scores are computed from (stored on every feature_snapshot).
FEATURE_SET_VERSION = "features-v0"

# Version of the output/envelope conventions themselves.
SCHEMA_CONVENTIONS_VERSION = "0.1.0"

# Sentinel used where a real model has not produced the value (e.g. health/status).
NO_MODEL = "n/a"
