"""Choosing what to show next.

Pure: no database, no clock, no randomness of its own. The caller supplies the candidate
pool, the recent history and the RNG, which is what makes every rule here unit-testable.
"""

import random
from collections.abc import Sequence
from typing import Final

# How far back a repeat still counts as a repeat. Matches the history table's retention.
HISTORY_WINDOW: Final[int] = 50

# The weight given to the artwork shown most recently. Deliberately not zero:
# docs/product-spec.md asks for a soft penalty, so that something seen two hours ago is
# unlikely rather than impossible.
MIN_WEIGHT: Final[float] = 0.02


def recency_weight(positions_ago: int | None, window: int = HISTORY_WINDOW) -> float:
    """How much to favour an artwork last shown `positions_ago` artworks back.

    1.0 means never seen, or seen longer ago than the window. The ramp between is linear:
    dull to explain is the point — see the scoring note in `docs/product-spec.md`.
    """
    if positions_ago is None or positions_ago >= window:
        return 1.0
    if positions_ago < 0:
        raise ValueError("positions_ago cannot be negative")
    return MIN_WEIGHT + (1.0 - MIN_WEIGHT) * (positions_ago / window)


def weighted_choice[T](items: Sequence[T], weights: Sequence[float], rng: random.Random) -> T:
    """Pick one item with probability proportional to its weight."""
    if not items:
        raise ValueError("cannot choose from an empty sequence")
    if len(items) != len(weights):
        raise ValueError("items and weights must be the same length")
    total = sum(weights)
    if total <= 0:
        # Every candidate was penalised to nothing. Fall back to uniform rather than
        # failing to show anything at all.
        return rng.choice(items)
    threshold = rng.random() * total
    cumulative = 0.0
    for item, weight in zip(items, weights, strict=True):
        cumulative += weight
        if cumulative >= threshold:
            return item
    return items[-1]  # pragma: no cover — floating-point tail


def choose_next[T](
    candidates: Sequence[T],
    candidate_ids: Sequence[int],
    recent_ids: Sequence[int],
    rng: random.Random,
    window: int = HISTORY_WINDOW,
) -> T:
    """Pick the next artwork, penalising anything shown recently.

    `recent_ids` is most-recent-first, which is how the history repository returns it.
    """
    if len(candidates) != len(candidate_ids):
        raise ValueError("candidates and candidate_ids must be the same length")
    # setdefault, not a comprehension: an artwork can appear in history more than once,
    # and the penalty must come from the most recent showing. A dict comprehension keeps
    # the last value written, which is the *oldest* occurrence and the weakest penalty —
    # exactly backwards.
    positions: dict[int, int] = {}
    for index, artwork_id in enumerate(recent_ids):
        positions.setdefault(artwork_id, index)
    weights = [recency_weight(positions.get(artwork_id), window) for artwork_id in candidate_ids]
    return weighted_choice(candidates, weights, rng)
