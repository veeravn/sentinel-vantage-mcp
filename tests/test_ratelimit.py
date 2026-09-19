"""Rolling-window rate limiter: burst up to N, then precise window pacing."""

from __future__ import annotations

import asyncio

from sentinel_vantage.core.ratelimit import RateLimiter


async def test_disabled_never_waits():
    rl = RateLimiter(0)
    for _ in range(100):
        await rl.acquire()  # no error, no pacing


async def test_bursts_up_to_limit_then_waits_for_window(monkeypatch):
    clock = {"t": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)
        clock["t"] += d  # advance the fake clock while "sleeping"

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    rl = RateLimiter(5, window_seconds=60.0, clock=lambda: clock["t"])

    # Idle -> a burst of 5 passes with no waiting.
    for _ in range(5):
        await rl.acquire()
    assert sleeps == []

    # The 6th must wait until the oldest (t=0) ages out of the 60s window.
    await rl.acquire()
    assert len(sleeps) == 1
    assert abs(sleeps[0] - 60.0) < 1e-6
    assert abs(clock["t"] - 60.0) < 1e-6  # clock advanced by the wait


async def test_never_exceeds_limit_in_any_window(monkeypatch):
    clock = {"t": 0.0}

    async def fake_sleep(d: float) -> None:
        clock["t"] += d

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    rl = RateLimiter(5, window_seconds=60.0, clock=lambda: clock["t"])
    stamps: list[float] = []
    for _ in range(12):
        await rl.acquire()
        stamps.append(clock["t"])

    # Verify no 60s window ever contains more than 5 requests.
    for t in stamps:
        in_window = [u for u in stamps if t - 60.0 < u <= t]
        assert len(in_window) <= 5
