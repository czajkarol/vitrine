"""Selection rules. Pure functions, so no mocks and no database."""

import random

import pytest

from app.domain.selection import (
    HISTORY_WINDOW,
    MIN_WEIGHT,
    choose_next,
    recency_weight,
    weighted_choice,
)


class TestRecencyWeight:
    def test_never_seen_is_unpenalised(self):
        assert recency_weight(None) == 1.0

    def test_older_than_the_window_is_unpenalised(self):
        assert recency_weight(HISTORY_WINDOW) == 1.0
        assert recency_weight(HISTORY_WINDOW + 500) == 1.0

    def test_the_most_recent_is_penalised_hardest(self):
        assert recency_weight(0) == pytest.approx(MIN_WEIGHT)

    def test_a_penalty_is_never_absolute(self):
        # docs/product-spec.md: unlikely, not impossible.
        assert recency_weight(0) > 0

    def test_weight_rises_with_distance(self):
        # Ordering, not exact values, so the ramp can be retuned without breaking this.
        weights = [recency_weight(n) for n in range(0, HISTORY_WINDOW, 5)]
        assert weights == sorted(weights)
        assert weights[0] < weights[-1]

    def test_rejects_a_negative_position(self):
        with pytest.raises(ValueError, match="negative"):
            recency_weight(-1)


class TestWeightedChoice:
    def test_favours_the_heavier_option(self):
        rng = random.Random(1234)
        picks = [weighted_choice(["heavy", "light"], [9.0, 1.0], rng) for _ in range(400)]
        assert picks.count("heavy") > picks.count("light") * 3

    def test_a_zero_weight_is_never_picked_against_a_positive_one(self):
        rng = random.Random(7)
        picks = {weighted_choice(["no", "yes"], [0.0, 1.0], rng) for _ in range(100)}
        assert picks == {"yes"}

    def test_all_zero_weights_still_returns_something(self):
        # Better a repeat than a blank screen.
        assert weighted_choice(["a", "b"], [0.0, 0.0], random.Random(3)) in {"a", "b"}

    def test_rejects_mismatched_lengths(self):
        with pytest.raises(ValueError, match="same length"):
            weighted_choice(["a"], [1.0, 2.0], random.Random())

    def test_rejects_an_empty_pool(self):
        with pytest.raises(ValueError, match="empty"):
            weighted_choice([], [], random.Random())


class TestChooseNext:
    def test_avoids_the_most_recently_shown(self):
        rng = random.Random(99)
        candidates = ["a", "b"]
        ids = [1, 2]
        picks = [choose_next(candidates, ids, [1], rng) for _ in range(300)]
        assert picks.count("b") > picks.count("a")

    def test_with_no_history_nothing_is_favoured(self):
        rng = random.Random(5)
        picks = [choose_next(["a", "b"], [1, 2], [], rng) for _ in range(400)]
        # Roughly even; the assertion is loose because this is a random process.
        assert 100 < picks.count("a") < 300

    def test_a_repeat_is_penalised_from_its_most_recent_showing(self):
        # History legitimately contains the same id twice. The penalty must come from the
        # latest showing, not the earliest one still in the window.
        rng = random.Random(11)
        history = [1, 2, 1, 1]  # id 1 was shown most recently
        picks = [choose_next(["a", "b"], [1, 2], history, rng) for _ in range(300)]
        assert picks.count("b") > picks.count("a")

    def test_returns_a_recent_artwork_when_it_is_the_only_one(self):
        assert choose_next(["a"], [1], [1], random.Random(2)) == "a"
