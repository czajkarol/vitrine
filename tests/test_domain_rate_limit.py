"""The token bucket and its hourly ceiling.

The clock is a list index, not `time.monotonic`. That is the whole reason the limiter takes
a clock: an hour of rolling window is testable in microseconds.
"""

from app.domain.rate_limit import RateLimiter


class FakeClock:
    """A monotonic clock that only moves when the test says so."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def limiter(clock: FakeClock, *, burst: int = 3, refill: float = 3.0, hourly: int = 0):
    return RateLimiter(burst=burst, refill_seconds=refill, hourly_limit=hourly, clock=clock)


class TestBurst:
    def test_a_full_bucket_lets_the_burst_through_back_to_back(self):
        limits = limiter(FakeClock(), burst=3)
        assert [limits.check().allowed for _ in range(3)] == [True, True, True]

    def test_and_refuses_the_one_after_it(self):
        limits = limiter(FakeClock(), burst=3)
        for _ in range(3):
            limits.check()
        assert limits.check().allowed is False

    def test_a_refusal_says_how_long_to_wait(self):
        limits = limiter(FakeClock(), burst=1, refill=3.0)
        limits.check()
        assert limits.check().retry_after_seconds == 3

    def test_the_wait_is_never_zero(self):
        """`Retry-After: 0` is an invitation to try immediately, which is the storm."""
        limits = limiter(FakeClock(), burst=1, refill=0.2)
        limits.check()
        assert limits.check().retry_after_seconds == 1


class TestRefill:
    def test_one_token_comes_back_per_refill_period(self):
        clock = FakeClock()
        limits = limiter(clock, burst=2, refill=3.0)
        limits.check()
        limits.check()
        assert limits.check().allowed is False

        clock.advance(3.0)
        assert limits.check().allowed is True
        assert limits.check().allowed is False

    def test_the_bucket_does_not_fill_past_its_burst(self):
        """An idle hour must not buy an hour's worth of requests all at once — that is
        the burst the limit exists to bound."""
        clock = FakeClock()
        limits = limiter(clock, burst=2, refill=3.0)
        clock.advance(3600.0)
        assert [limits.check().allowed for _ in range(3)] == [True, True, False]

    def test_a_clock_that_does_not_move_still_drains(self):
        limits = limiter(FakeClock(), burst=2, refill=3.0)
        assert [limits.check().allowed for _ in range(3)] == [True, True, False]


class TestHourlyCeiling:
    def test_the_ceiling_stops_a_bucket_that_would_otherwise_run_forever(self):
        clock = FakeClock()
        limits = limiter(clock, burst=1, refill=1.0, hourly=5)
        allowed = 0
        # Two hundred seconds at one per second: the bucket alone would pass all of them.
        for _ in range(200):
            if limits.check().allowed:
                allowed += 1
            clock.advance(1.0)
        assert allowed == 5

    def test_the_wait_is_until_the_oldest_request_ages_out(self):
        """Not the bucket's three seconds. Reporting that would send the caller back to
        be refused again, which is the behaviour Retry-After exists to prevent."""
        clock = FakeClock()
        limits = limiter(clock, burst=10, refill=1.0, hourly=2)
        limits.check()
        clock.advance(10.0)
        limits.check()

        clock.advance(10.0)
        decision = limits.check()
        assert decision.allowed is False
        # The first request was 20s ago, so it leaves the window in 3580s.
        assert decision.retry_after_seconds == 3580

    def test_requests_leave_the_window_after_an_hour(self):
        clock = FakeClock()
        limits = limiter(clock, burst=10, refill=1.0, hourly=2)
        limits.check()
        limits.check()
        assert limits.check().allowed is False

        clock.advance(3601.0)
        assert limits.check().allowed is True

    def test_a_refused_request_does_not_count_against_the_window(self):
        """Otherwise a client that keeps asking keeps its own lockout alive forever."""
        clock = FakeClock()
        limits = limiter(clock, burst=10, refill=1.0, hourly=1)
        limits.check()
        for _ in range(50):
            limits.check()

        clock.advance(3601.0)
        assert limits.check().allowed is True


class TestDisabled:
    def test_zero_burst_allows_everything(self):
        """A legitimate configuration, not an error: a machine nobody else can reach."""
        limits = limiter(FakeClock(), burst=0, hourly=1)
        assert all(limits.check().allowed for _ in range(100))
        assert limits.enabled is False

    def test_zero_hourly_limit_leaves_only_the_bucket(self):
        clock = FakeClock()
        limits = limiter(clock, burst=1, refill=1.0, hourly=0)
        for _ in range(500):
            assert limits.check().allowed is True
            clock.advance(1.0)


class TestDependentRequests:
    """An advance is two requests — the artwork, then its image through the proxy. The
    unit being limited is the advance."""

    def test_an_allowed_request_grants_its_dependent_one(self):
        limits = limiter(FakeClock(), burst=1, refill=30.0)
        assert limits.check().allowed is True
        assert limits.check(dependent=True).allowed is True

    def test_a_dependent_request_with_no_credit_pays_full_price(self):
        """Otherwise the credit is a way around the limit rather than an accounting of
        what one advance costs."""
        limits = limiter(FakeClock(), burst=1, refill=30.0)
        limits.check()
        limits.check(dependent=True)
        assert limits.check(dependent=True).allowed is False

    def test_credits_do_not_accumulate_past_the_burst(self):
        """An hour of granted advances must not bank an hour's worth of free image
        fetches to spend all at once later."""
        clock = FakeClock()
        limits = limiter(clock, burst=2, refill=1.0)
        for _ in range(20):
            limits.check()
            clock.advance(1.0)

        # Empty the bucket, so what follows is answered by credits and nothing else.
        while limits.check().allowed:
            pass

        assert [limits.check(dependent=True).allowed for _ in range(3)] == [True, True, False]

    def test_a_dependent_request_does_not_spend_the_hourly_ceiling_twice(self):
        """The ceiling counts advances. Charging the image again would halve it, and the
        number in .env would mean half of what it says."""
        clock = FakeClock()
        limits = limiter(clock, burst=10, refill=1.0, hourly=3)
        for _ in range(3):
            assert limits.check().allowed is True
            assert limits.check(dependent=True).allowed is True
            clock.advance(5.0)
        assert limits.check().allowed is False
