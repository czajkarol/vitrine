"""A circuit breaker: stop calling something that keeps failing.

Pure, with the clock injected. Time is the only thing this needs from the outside world,
and taking it as an argument is what lets the cooling period be tested without waiting out
five real minutes.

The point is not politeness to the provider. A provider that has been failing for the last
five calls will almost certainly fail on the sixth, and every attempt costs a timeout the
user waits through — so the breaker mostly buys back the display's responsiveness.
"""

import time
from collections.abc import Callable
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    """Working. Calls go through."""

    OPEN = "open"
    """Failing. Calls are refused until the cooling period elapses."""

    HALF_OPEN = "half_open"
    """The cooling period is over and one call may try. Its result decides which way the
    circuit goes next — a single failure reopens immediately rather than spending the
    whole threshold again."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param threshold: consecutive failures before opening. Zero or less disables the
            breaker entirely, which is a legitimate configuration and not an error.
        :param cooldown_seconds: how long to stay open.
        :param clock: monotonic seconds. Injected so tests need not sleep, and monotonic
            so a system clock change cannot leave the circuit open for a decade.
        """
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._clock() - self._opened_at >= self._cooldown:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allows(self) -> bool:
        """Whether a call may be attempted now."""
        if self._threshold <= 0:
            return True
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Forget the failure history.

        For when the thing behind the breaker has changed rather than recovered — a new
        API key is not the provider that was failing a minute ago, and making the user
        wait out a cooling period earned by the old one would look like the new key was
        rejected.
        """
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Count one failure, and open if that was enough.

        A failure while half-open reopens straight away: the trial call was the question,
        and it has been answered.
        """
        if self._threshold <= 0:
            return
        if self.state is CircuitState.HALF_OPEN:
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    def seconds_until_retry(self) -> float:
        """How long until a call would be allowed. Zero when one already is."""
        if self._opened_at is None or not self._cooldown:
            return 0.0
        remaining = self._cooldown - (self._clock() - self._opened_at)
        return max(0.0, remaining)
