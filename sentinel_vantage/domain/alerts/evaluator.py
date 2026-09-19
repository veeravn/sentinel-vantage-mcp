"""Pure rule-DSL evaluation.

Deterministic and side-effect free so rules are testable and replayable. A condition on
a metric that is missing (or None) evaluates to False — a rule never fires on absent
data.
"""

from __future__ import annotations

import operator
from collections.abc import Mapping

from sentinel_vantage.domain.alerts.models import Condition, RuleDSL

_OPS = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def _passes(cond: Condition, metrics: Mapping[str, float]) -> bool:
    value = metrics.get(cond.metric)
    if value is None:
        return False
    return bool(_OPS[cond.op](value, cond.value))


def evaluate_rule(rule: RuleDSL, metrics: Mapping[str, float]) -> bool:
    """True if the rule fires for these metric values."""
    if not rule.all and not rule.any:
        return False  # an empty rule never fires
    all_ok = all(_passes(c, metrics) for c in rule.all)
    any_ok = any(_passes(c, metrics) for c in rule.any) if rule.any else True
    return all_ok and any_ok


def evaluated_metrics(rule: RuleDSL, metrics: Mapping[str, float]) -> dict[str, float]:
    """The referenced metric values that were present — stored on the alert for audit."""
    return {m: metrics[m] for m in rule.referenced_metrics() if metrics.get(m) is not None}
