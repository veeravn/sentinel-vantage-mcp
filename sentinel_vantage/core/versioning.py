"""Model and schema versions recorded on every persisted snapshot. Bumping a version is
a new interpretation, never a mutation of existing rows — never reuse a string after its
logic changes."""

from __future__ import annotations

TREND_MODEL_VERSION = "trend-v0"
RESEARCH_MODEL_VERSION = "research-v0"
CATALYST_MODEL_VERSION = "catalyst-v0"
FEATURE_SET_VERSION = "features-v0"
SCHEMA_CONVENTIONS_VERSION = "0.1.0"

# Sentinel for outputs with no scoring model (e.g. health/status).
NO_MODEL = "n/a"
