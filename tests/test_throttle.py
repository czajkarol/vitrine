"""The rate limiter. AIC allows 60/min and there is no key to raise it."""

import asyncio

import pytest

from app.providers.aic.throttle import RateLimiter


class TestRateLimiter:
    async def test_allows_requests_up_to_the_limit_without_waiting(self):
        limiter = RateLimiter(max_per_minute=5)
        start = asyncio.get_running_loop().time()
        for _ in range(5):
            await limiter.acquire()
        assert asyncio.get_running_loop().time() - start < 0.1

    async def test_blocks_once_the_window_is_full(self):
        # A short window keeps the test fast while exercising the real waiting path.
        limiter = RateLimiter(max_per_minute=2, window_seconds=0.3)
        await limiter.acquire()
        await limiter.acquire()

        start = asyncio.get_running_loop().time()
        await limiter.acquire()
        waited = asyncio.get_running_loop().time() - start
        assert waited >= 0.2, "third acquisition should have waited for the window to slide"

    async def test_slots_free_up_as_the_window_slides(self):
        limiter = RateLimiter(max_per_minute=2, window_seconds=0.2)
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.available == 0
        await asyncio.sleep(0.25)
        assert limiter.available == 2

    async def test_concurrent_callers_do_not_exceed_the_limit(self):
        limiter = RateLimiter(max_per_minute=3, window_seconds=0.4)
        acquired: list[float] = []

        async def worker():
            await limiter.acquire()
            acquired.append(asyncio.get_running_loop().time())

        await asyncio.gather(*(worker() for _ in range(6)))

        assert len(acquired) == 6
        # The first three go straight through; the rest wait for the window to slide.
        assert acquired[3] - acquired[0] >= 0.3

    def test_rejects_a_nonsensical_limit(self):
        with pytest.raises(ValueError, match="at least 1"):
            RateLimiter(max_per_minute=0)
