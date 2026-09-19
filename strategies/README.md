# Strategy configurations

Version-controlled, immutable strategy definitions (gates, factor weights, risk
penalties, minimum confidence). Populated in Phase 2 — GARP first.

Once a strategy version has been used in a persisted score snapshot it is **frozen**:
changing weights creates a new `score_version` rather than altering the meaning of
historical scores. See design sections 10.4 and 26.
