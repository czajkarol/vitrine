"""The circuit breaker, with a clock we control.

No test here sleeps. The cooling period is five minutes by default and waiting one out
would make the suite useless, which is the reason the clock is injected in the first place.
"""

from app.domain.circuit_breaker import CircuitBreaker, CircuitState


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(threshold=3, cooldown=300.0):
    clock = FakeClock()
    return CircuitBreaker(threshold=threshold, cooldown_seconds=cooldown, clock=clock), clock


class TestOpening:
    def test_starts_closed(self):
        breaker, _ = _breaker()
        assert breaker.state is CircuitState.CLOSED
        assert breaker.allows()

    def test_stays_closed_below_the_threshold(self):
        breaker, _ = _breaker(threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.allows()

    def test_opens_on_the_threshold_failure(self):
        breaker, _ = _breaker(threshold=3)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state is CircuitState.OPEN
        assert not breaker.allows()

    def test_a_success_resets_the_count(self):
        breaker, _ = _breaker(threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        breaker.record_failure()
        breaker.record_failure()
        # Consecutive means consecutive. Two failures either side of a success are not
        # four in a row.
        assert breaker.allows()


class TestCoolingDown:
    def test_refuses_for_the_whole_cooling_period(self):
        breaker, clock = _breaker(threshold=1, cooldown=300.0)
        breaker.record_failure()
        clock.advance(299)
        assert not breaker.allows()

    def test_allows_a_trial_call_once_the_period_is_over(self):
        breaker, clock = _breaker(threshold=1, cooldown=300.0)
        breaker.record_failure()
        clock.advance(300)
        assert breaker.state is CircuitState.HALF_OPEN
        assert breaker.allows()

    def test_a_failed_trial_reopens_immediately(self):
        breaker, clock = _breaker(threshold=5, cooldown=300.0)
        for _ in range(5):
            breaker.record_failure()
        clock.advance(300)

        breaker.record_failure()
        # The trial call was the question and it has been answered. Spending another five
        # failures to ask again would mean five more timeouts the user waits through.
        assert breaker.state is CircuitState.OPEN
        assert not breaker.allows()

    def test_a_successful_trial_closes_the_circuit(self):
        breaker, clock = _breaker(threshold=2, cooldown=300.0)
        breaker.record_failure()
        breaker.record_failure()
        clock.advance(300)

        breaker.record_success()
        assert breaker.state is CircuitState.CLOSED
        assert breaker.consecutive_failures == 0

    def test_reports_how_long_is_left(self):
        breaker, clock = _breaker(threshold=1, cooldown=300.0)
        breaker.record_failure()
        clock.advance(120)
        assert breaker.seconds_until_retry() == 180.0

    def test_reports_nothing_left_when_a_call_is_allowed(self):
        breaker, _ = _breaker()
        assert breaker.seconds_until_retry() == 0.0


class TestDisabled:
    def test_a_zero_threshold_never_opens(self):
        # A legitimate configuration, not an error: someone who would rather every call
        # were attempted.
        breaker, _ = _breaker(threshold=0)
        for _ in range(50):
            breaker.record_failure()
        assert breaker.allows()
        assert breaker.state is CircuitState.CLOSED
