"""Async rolling-window rate limiter: at most N requests in any rolling W-second window,
waiting until the oldest ages out when full. A non-positive rate disables it. A token
bucket is deliberately avoided — its post-burst refill still trips the API's limit."""

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
