"""TrendService end-to-end over the in-memory repository (offline replay pipeline)."""

from __future__ import annotations

from conftest import make_daily_bars

from sentinel_vantage.domain.trend.service import TrendService
from sentinel_vantage.storage.memory import InMemoryBarRepository, InMemoryScoreRepository


def _repo() -> InMemoryBarRepository:
    histories = {
        "SPY": make_daily_bars("SPY", [100.0] * 70, [50_000_000.0] * 70),
        "HOT": make_daily_bars("HOT", [100.0] * 69 + [112.0], [1_000_000.0] * 69 + [4_000_000.0]),
        "MID": make_daily_bars("MID", [100.0] * 69 + [101.0], [1_000_000.0] * 70),
        "COLD": make_daily_bars("COLD", [100.0] * 69 + [96.0], [1_000_000.0] * 69 + [500_000.0]),
        # PENNY fails the price gate -> should be ineligible, excluded from ranking.
        "PENNY": make_daily_bars("PENNY", [1.2] * 69 + [1.6], [30_000_000.0] * 70),
    }
    return InMemoryBarRepository(histories)


def _as_of(repo):
    return repo._histories["HOT"][-1].ts


async def test_scan_ranks_and_excludes_ineligible():
    repo = _repo()
    svc = TrendService(repo)
    scan = await svc.scan(as_of=_as_of(repo), limit=10)

    ranked = [r.symbol for r in scan.results]
    assert ranked[0] == "HOT"
    assert "PENNY" not in ranked  # AT-3: gate failure keeps it out of the strategy ranking
    assert any(e.symbol == "PENNY" for e in scan.ineligible)
    assert scan.universe_size == 4  # SPY excluded from the scored universe


async def test_scan_is_deterministic_replay():
    # AT-1 at the pipeline level: two identical scans produce identical output.
    repo = _repo()
    svc = TrendService(repo)
    a = await svc.scan(as_of=_as_of(repo), limit=10)
    b = await svc.scan(as_of=_as_of(repo), limit=10)
    assert a.model_dump(mode="json") == b.model_dump(mode="json")


async def test_min_confidence_filter():
    repo = _repo()
    svc = TrendService(repo)
    # Short history (< 120 days) lowers the history factor, so nothing clears 0.99.
    scan = await svc.scan(as_of=_as_of(repo), min_confidence=0.99)
    assert scan.results == []


async def test_analyze_eligible_and_ineligible():
    repo = _repo()
    svc = TrendService(repo)
    hot = await svc.analyze("HOT", as_of=_as_of(repo))
    assert hot.eligible and hot.result is not None and hot.result.symbol == "HOT"

    penny = await svc.analyze("PENNY", as_of=_as_of(repo))
    assert not penny.eligible
    assert penny.gate_failures


async def test_persist_and_history_roundtrip():
    repo = _repo()
    scores = InMemoryScoreRepository()
    svc = TrendService(repo, scores=scores)
    as_of = _as_of(repo)
    await svc.scan(as_of=as_of, persist=True)

    hist = await svc.score_history("HOT", horizon="1d", start=as_of.replace(hour=0), end=as_of)
    assert len(hist) == 1
    assert hist[0].symbol == "HOT"
