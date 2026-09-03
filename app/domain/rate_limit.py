"""A token bucket, and an hourly ceiling over it.

Pure, with the clock passed in — the same shape as `circuit_breaker.py`, and for the same
reason: a limiter that reads its own clock can only be tested by waiting.

**What this is protecting, and what it is not.** With an index present, serving an artwork
makes no AIC call at all (ADR-0003). The outbound cost of an advance is one IIIF image
fetch, either straight from the browser or through `GET /api/image/{image_id}`. So this is
not about AIC's documented 60 requests/minute, which the index already keeps us far below.
It is about not leaning on someone else's CDN, and about bounding a tab that has got stuck
in a retry loop overnight — a local app with one user still runs unattended for hours,
which is the whole point of it.

Two limits, because they answer different questions:

- The **bucket** answers "how fast may this go right now". A burst is allowed and then the
  rate settles, which is what a human pressing "next" repeatedly actually looks like.
- The **hourly ceiling** answers "how much in total". A bucket alone permits its sustained
  rate forever, and forever is exactly the failure mode a display left running has.

**And a credit, which is what stops the limiter causing the storm it prevents.** Showing one
artwork is two requests: the browser asks for the artwork, and then — when the direct IIIF
load has been blocked — for its image through our proxy. Charging both meant an advance
could be granted and its image refused, and an `<img>` cannot see a `429`: the display reads
a refused image as a dead one, drops the artwork and immediately asks for another. Measured
in a browser, and it does not recover on its own.

So an allowed artwork request grants one credit, and the image proxy spends a credit before
it spends a token. The unit being limited is an advance, not an HTTP request. A proxy call
with no advance behind it — a stuck loop on one image id — still pays full price.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class Decision:
    """Whether a request may proceed, and if not, how long to wait.

    `retry_after_seconds` is what goes in the `Retry-After` header, so it is always at
    least 1: the header is expressed in whole seconds and a `0` invites an immediate retry,
    which is the retry storm this exists to prevent.
    """

    allowed: bool
    retry_after_seconds: int = 0


ALLOWED = Decision(allowed=True)


class RateLimiter:
    """A token bucket with an hourly ceiling. Not thread-safe, and does not need to be:
    it is called from the event loop thread and every method is synchronous and short."""

    def __init__(
        self,
        *,
        burst: int,
        refill_seconds: float,
        hourly_limit: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        :param burst: bucket capacity, and how many requests may go through back to back.
        :param refill_seconds: seconds per token. 3.0 is one every three seconds, so 20 a
            minute sustained.
        :param hourly_limit: requests allowed in any rolling hour. Zero or less means no
            ceiling; `burst` of zero or less disables the limiter entirely, which is a
            legitimate configuration and not an error.
        :param clock: monotonic seconds. Monotonic so that a system clock change cannot
            lock the display out until the clock catches up.
        """
        self._burst = burst
        self._refill = refill_seconds
        self._hourly_limit = hourly_limit
        self._clock = clock
        self._tokens = float(burst)
        self._last = clock()
        # Timestamps of allowed requests inside the last hour. Bounded by hourly_limit,
        # so at the proposed 400 it is a few kilobytes and never grows past that.
        self._recent: deque[float] = deque()
        # Images owed to advances already granted. Capped at the burst so an idle hour of
        # granted advances cannot bank an unbounded right to fetch images later.
        self._credits = 0

    @property
    def enabled(self) -> bool:
        return self._burst > 0

    def check(self, *, dependent: bool = False) -> Decision:
        """Take a token if there is one. Call once per request, and only once — this
        mutates.

        :param dependent: this request completes work already allowed — the image for an
            artwork just served. It spends a credit rather than a token, and does not
            count against the hourly ceiling, because the advance it belongs to already
            did. With no credit left it is charged like anything else.
        """
        if not self.enabled:
            return ALLOWED

        if dependent and self._credits > 0:
            self._credits -= 1
            return ALLOWED

        now = self._clock()
        self._refill_to(now)
        self._forget_older_than(now - 3600.0)

        if self._hourly_limit > 0 and len(self._recent) >= self._hourly_limit:
            # The oldest request in the window is what has to age out before there is
            # room. Reporting the bucket's wait here instead would send the caller back
            # in three seconds to be refused again.
            oldest = self._recent[0]
            wait = oldest + 3600.0 - now
            return Decision(allowed=False, retry_after_seconds=_whole_seconds(wait))

        if self._tokens < 1.0:
            return Decision(
                allowed=False,
                retry_after_seconds=_whole_seconds((1.0 - self._tokens) * self._refill),
            )

        self._tokens -= 1.0
        self._recent.append(now)
        if not dependent:
            self._credits = min(self._burst, self._credits + 1)
        return ALLOWED

    def _refill_to(self, now: float) -> None:
        elapsed = max(0.0, now - self._last)
        self._last = now
        if self._refill <= 0:
            self._tokens = float(self._burst)
            return
        self._tokens = min(float(self._burst), self._tokens + elapsed / self._refill)

    def _forget_older_than(self, cutoff: float) -> None:
        while self._recent and self._recent[0] <= cutoff:
            self._recent.popleft()


def _whole_seconds(seconds: float) -> int:
    """Round a wait up to whole seconds, never below 1.

    Up, because rounding down hands back a deadline that has not passed yet and the very
    next request is refused again. Never below 1, because `Retry-After: 0` is an
    invitation to try immediately.
    """
    return max(1, ceil(seconds))
