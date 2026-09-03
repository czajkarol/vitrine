"""A sliding-window rate limiter.

AIC allows 60 requests/minute per IP for anonymous clients and there is no API key to
raise that. Exceeding it is our problem to prevent, not theirs to absorb.
"""

import asyncio
import time
from collections import deque
from types import TracebackType


class RateLimiter:
    """Allows at most `max_per_minute` acquisitions in any 60-second window.

    A sliding window rather than a fixed one: a fixed window lets 2x the limit through at
    a boundary, which is exactly the burst that gets an IP throttled.
    """

    def __init__(self, max_per_minute: int, window_seconds: float = 60.0) -> None:
        if max_per_minute < 1:
            raise ValueError("max_per_minute must be at least 1")
        self._max = max_per_minute
        self._window = window_seconds
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request may be made, then record it."""
        while True:
            async with self._lock:
                now = time.monotonic()
                self._evict(now)
                if len(self._hits) < self._max:
                    self._hits.append(now)
                    return
                # Sleep until the oldest hit leaves the window. Computed inside the lock,
                # awaited outside it, so waiters do not serialise behind each other.
                wait = self._window - (now - self._hits[0])
            await asyncio.sleep(max(wait, 0.001))

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()

    @property
    def available(self) -> int:
        """Slots free right now. For diagnostics; do not gate requests on this."""
        self._evict(time.monotonic())
        return max(self._max - len(self._hits), 0)

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
