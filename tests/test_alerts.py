"""Alert rule DSL evaluation and the alert engine (dedup/cooldown), offline."""

from __future__ import annotations

import itertools
from datetime import timedelta

from conftest import make_daily_bars

from sentinel_vantage.domain.alerts.engine import AlertEngine
from sentinel_vantage.domain.alerts.evaluator import evaluate_rule
from sentinel_vantage.domain.alerts.models import AlertRule, Condition, RuleDSL, Watchlist
from sentinel_vantage.domain.alerts.resolver import MetricResolver
from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.memory import (
    InMemoryAlertEventRepository,
    InMemoryAlertRuleRepository,
    InMemoryBarRepository,
    InMemoryWatchlistRepository,
)


def _rule(conds, *, any_conds=None, cooldown=4.0):
    return RuleDSL(
        all=[Condition(**c) for c in conds],
        any=[Condition(**c) for c in (any_conds or [])],
        cooldown_hours=cooldown,
    )


def test_evaluate_all_and_any():
    rule = _rule(
        [{"metric": "trend_score", "op": ">=", "value": 80}],
        any_conds=[
            {"metric": "volume_ratio", "op": ">=", "value": 2.0},
            {"metric": "return_1d_pct", "op": ">=", "value": 5.0},
        ],
    )
    assert evaluate_rule(rule, {"trend_score": 90, "volume_ratio": 3.0}) is True
    assert (
        evaluate_rule(rule, {"trend_score": 90, "volume_ratio": 1.0, "return_1d_pct": 6.0}) is True
    )
    assert evaluate_rule(rule, {"trend_score": 70, "volume_ratio": 3.0}) is False  # all fails
    assert evaluate_rule(rule, {"trend_score": 90}) is False  # any unmet (both missing)


def test_missing_metric_never_fires():
    rule = _rule([{"metric": "research_score:GARP", "op": ">=", "value": 75}])
    assert evaluate_rule(rule, {"trend_score": 99}) is False


def test_empty_rule_never_fires():
    assert evaluate_rule(RuleDSL(), {"trend_score": 100}) is False


def _engine_setup():
    bars = InMemoryBarRepository(
        {
            "SPY": make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70),
            "HOT": make_daily_bars(
                "HOT", [100.0] * 69 + [108.0], [1_000_000.0] * 69 + [4_000_000.0]
            ),
            "MID": make_daily_bars("MID", [100.0] * 70, [1_000_000.0] * 70),
        }
    )
    rules = InMemoryAlertRuleRepository()
    events = InMemoryAlertEventRepository()
    resolver = MetricResolver(TrendService(bars))
    counter = itertools.count()
    engine = AlertEngine(rules, events, resolver, id_factory=lambda: f"ev{next(counter)}")
    return bars, rules, events, engine


async def test_engine_fires_and_cooldown_dedups():
    _, rules, events, engine = _engine_setup()
    as_of = make_daily_bars("HOT", [1.0] * 70)[-1].ts
    await rules.save_rule(
        AlertRule(
            rule_id="r1",
            symbols=["HOT", "MID"],
            rule=_rule([{"metric": "volume_ratio", "op": ">=", "value": 2.0}]),
            severity="warning",
            created_at=as_of,
        )
    )

    fired = await engine.run_once(as_of=as_of)
    assert [e.symbol for e in fired] == ["HOT"]  # only HOT has abnormal volume
    assert fired[0].severity == "warning"
    assert fired[0].metrics["volume_ratio"] == 4.0  # evaluated value stored for audit

    # Immediate re-run: within cooldown -> no duplicate alert.
    again = await engine.run_once(as_of=as_of + timedelta(minutes=1))
    assert again == []

    # After the cooldown window -> fires again.
    later = await engine.run_once(as_of=as_of + timedelta(hours=5))
    assert [e.symbol for e in later] == ["HOT"]


async def test_engine_resolves_watchlist_symbols():
    bars, rules, events, engine = _engine_setup()
    watchlists = InMemoryWatchlistRepository()
    engine.watchlists = watchlists
    as_of = make_daily_bars("HOT", [1.0] * 70)[-1].ts
    await watchlists.save_watchlist(
        Watchlist(watchlist_id="w1", name="mine", symbols=["HOT"], created_at=as_of)
    )
    await rules.save_rule(
        AlertRule(
            rule_id="r2",
            watchlist_id="w1",
            rule=_rule([{"metric": "volume_ratio", "op": ">=", "value": 2.0}]),
            created_at=as_of,
        )
    )
    fired = await engine.run_once(as_of=as_of)
    assert [e.symbol for e in fired] == ["HOT"]


async def test_list_events_filters():
    _, rules, events, engine = _engine_setup()
    as_of = make_daily_bars("HOT", [1.0] * 70)[-1].ts
    await rules.save_rule(
        AlertRule(
            rule_id="r3",
            symbols=["HOT"],
            severity="critical",
            rule=_rule([{"metric": "volume_ratio", "op": ">=", "value": 2.0}]),
            created_at=as_of,
        )
    )
    await engine.run_once(as_of=as_of)
    since = as_of - timedelta(days=1)
    assert len(await events.list_events(since=since)) == 1
    assert len(await events.list_events(since=since, severity="critical")) == 1
    assert len(await events.list_events(since=since, severity="info")) == 0
    assert len(await events.list_events(since=since, symbols=["MID"])) == 0
