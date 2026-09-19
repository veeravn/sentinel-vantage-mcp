"""Async rolling-window rate limiter.

Paces outbound requests to stay under a provider's quota *before* hitting it, matching
the way APIs like Polygon enforce "at most N requests in any rolling W-second window".
It records recent request times and, when the window is full, waits exactly until the
oldest one ages out. This allows a legitimate burst of up to N when idle, then a precise
cadence — without ever exceeding N per window. A non-positive rate disables it (paid
tiers with no meaningful limit).

A token bucket is deliberately NOT used: after an initial burst it refills faster than a
rolling window allows, so the request just past the burst still trips the API's limit.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        rate_per_minute: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = rate_per_minute > 0
        self.limit = rate_per_minute
        self.window = window_seconds
        self._clock = clock
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until a request may proceed under the rolling window, then record it."""
        if not self.enabled:
            return
        async with self._lock:
            while True:
                now = self._clock()
                cutoff = now - self.window
                while self._times and self._times[0] <= cutoff:
                    self._times.popleft()
                if len(self._times) < self.limit:
                    self._times.append(now)
                    return
                # Window full: wait until the oldest request ages out.
                await asyncio.sleep(self._times[0] + self.window - now)
