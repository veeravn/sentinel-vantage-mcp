"""Parse "metric op value" condition strings (e.g. "trend_score >= 85",
"research_score:GARP >= 75") into structured, validated Conditions."""

from __future__ import annotations

import re

from sentinel_vantage.domain.alerts.models import Condition

_RE = re.compile(r"^\s*([A-Za-z0-9_:.\-]+)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_condition(text: str) -> Condition:
    m = _RE.match(text)
    if not m:
        raise ValueError(
            f"Invalid condition {text!r}; expected 'metric op value' (e.g. 'trend_score >= 85')."
        )
    return Condition(metric=m.group(1), op=m.group(2), value=float(m.group(3)))


def parse_conditions(texts: list[str]) -> list[Condition]:
    return [parse_condition(t) for t in texts]
