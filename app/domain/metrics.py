"""Counting things, so `/api/stats` has something honest to report.

Three shapes, all pure and all trivially testable, because the alternative — a metrics
library — would be the largest dependency in the project to answer three questions.

Everything here counts from process start and lives in memory. That is a deliberate limit,
not an oversight: these numbers exist to answer "is the cache working, is the provider
slow, is AIC flaking" while the display is running, and a restart is the honest place for
that question to begin again. What must survive a restart — the daily AI spend — is in
`ai_usage`, in SQLite, where the budget guard can enforce it.

`domain/` means no I/O and no clock of its own: durations are handed in, already measured.
"""

from dataclasses import dataclass


@dataclass
class Tally:
    """Successes and failures of the same thing, and the rate between them."""

    total: int = 0
    errors: int = 0

    def record(self, *, error: bool = False) -> None:
        self.total += 1
        if error:
            self.errors += 1

    @property
    def error_rate(self) -> float:
        """Errors as a fraction of everything attempted. Zero when nothing has been."""
        return self.errors / self.total if self.total else 0.0


@dataclass
class CacheTally:
    """Hits and misses. Kept separate from `Tally` because a miss is not an error —
    the first time anyone asks about an artwork it is *supposed* to miss."""

    hits: int = 0
    misses: int = 0

    def record(self, *, hit: bool) -> None:
        if hit:
            self.hits += 1
        else:
            self.misses += 1

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0


@dataclass
class LatencySummary:
    """How long something took, without keeping every sample.

    Count, total and maximum — enough for a mean and a worst case, and bounded in memory
    however long the display runs. A percentile would need the samples, and this is a
    single-user app looking at one provider: the maximum is the tail.
    """

    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0

    def record(self, elapsed_ms: float) -> None:
        self.count += 1
        self.total_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)

    @property
    def average_ms(self) -> float:
        return self.total_ms / self.count if self.count else 0.0
