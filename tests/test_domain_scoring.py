"""Curated scoring. Ordering only — never exact floats, so weights stay tunable."""

import pytest

from app.domain.artwork import Artwork, Thumbnail
from app.domain.scoring import (
    RESOLUTION_CEILING,
    WEIGHTS,
    aspect_ratio_signal,
    explain,
    metadata_completeness_signal,
    score,
    signals,
)


def _artwork(**overrides) -> Artwork:
    base = {
        "id": 1,
        "title": "A work",
        "image_id": "abc",
        "is_public_domain": True,
        "thumbnail": Thumbnail(width=1600, height=900, alt_text="a description"),
        "artist_title": "An artist",
        "date_display": "1900",
        "medium_display": "Oil on canvas",
        "description": "<p>Some prose.</p>",
        "artwork_type_title": "Painting",
    }
    return Artwork(**{**base, **overrides})


class TestScoreShape:
    def test_stays_within_zero_and_one(self):
        best = _artwork(is_boosted=True, thumbnail=Thumbnail(width=3400, height=1912, alt_text="x"))
        worst = _artwork(
            is_boosted=False,
            thumbnail=Thumbnail(width=850, height=4000),
            artist_title=None,
            date_display=None,
            medium_display=None,
            description=None,
            artwork_type_title="Coin",
        )
        for artwork in (best, worst):
            assert 0.0 <= score(artwork) <= 1.0
        assert score(best) > score(worst)

    def test_every_weight_has_a_signal(self):
        # A weight with no matching signal would silently contribute nothing.
        assert set(signals(_artwork())) == set(WEIGHTS)


class TestRanking:
    def test_a_boosted_work_outranks_an_identical_unboosted_one(self):
        assert score(_artwork(is_boosted=True)) > score(_artwork(is_boosted=False))

    def test_a_bigger_original_outranks_a_smaller_one(self):
        big = _artwork(thumbnail=Thumbnail(width=3000, height=1688, alt_text="x"))
        small = _artwork(thumbnail=Thumbnail(width=900, height=506, alt_text="x"))
        assert score(big) > score(small)

    def test_a_screen_shaped_work_outranks_a_narrow_one(self):
        wide = _artwork(thumbnail=Thumbnail(width=1600, height=900, alt_text="x"))
        tall = _artwork(thumbnail=Thumbnail(width=600, height=2400, alt_text="x"))
        assert score(wide) > score(tall)

    def test_a_fully_captioned_work_outranks_a_bare_one(self):
        bare = _artwork(artist_title=None, date_display=None, medium_display=None, description=None)
        assert score(_artwork()) > score(bare)

    def test_alt_text_helps(self):
        with_alt = _artwork(thumbnail=Thumbnail(width=1600, height=900, alt_text="described"))
        without = _artwork(thumbnail=Thumbnail(width=1600, height=900))
        assert score(with_alt) > score(without)

    def test_a_painting_outranks_a_coin(self):
        assert score(_artwork(artwork_type_title="Painting")) > score(
            _artwork(artwork_type_title="Coin")
        )

    def test_an_unknown_type_lands_between_the_extremes(self):
        unknown = score(_artwork(artwork_type_title="Something AIC Invented"))
        assert score(_artwork(artwork_type_title="Coin")) < unknown
        assert unknown < score(_artwork(artwork_type_title="Painting"))

    def test_ranking_a_mixed_set_is_stable_and_sensible(self):
        masterpiece = _artwork(
            id=1, is_boosted=True, thumbnail=Thumbnail(width=3000, height=1700, alt_text="x")
        )
        decent = _artwork(id=2)
        poor = _artwork(
            id=3,
            thumbnail=Thumbnail(width=850, height=3000),
            artist_title=None,
            description=None,
            artwork_type_title="Furniture",
        )
        ranked = sorted([decent, poor, masterpiece], key=score, reverse=True)
        assert [a.id for a in ranked] == [1, 2, 3]


class TestMissingData:
    def test_unknown_dimensions_score_neutrally_rather_than_worst(self):
        unknown = _artwork(thumbnail=Thumbnail(alt_text="x"))
        tiny = _artwork(thumbnail=Thumbnail(width=100, height=100, alt_text="x"))
        assert score(unknown) > score(tiny)

    def test_no_thumbnail_at_all_does_not_raise(self):
        assert 0.0 <= score(_artwork(thumbnail=None)) <= 1.0

    def test_aspect_signal_is_neutral_without_dimensions(self):
        assert aspect_ratio_signal(_artwork(thumbnail=None)) == 0.5

    def test_completeness_counts_present_fields(self):
        assert metadata_completeness_signal(_artwork()) == 1.0
        empty = _artwork(
            artist_title=None, date_display=None, medium_display=None, description=None
        )
        assert metadata_completeness_signal(empty) == 0.0


class TestAspectRatio:
    def test_matching_the_viewport_scores_highest(self):
        square = _artwork(thumbnail=Thumbnail(width=1000, height=1000))
        assert aspect_ratio_signal(square, viewport_ratio=1.0) == pytest.approx(1.0)

    def test_a_panorama_and_a_scroll_equally_far_off_score_the_same(self):
        wide = _artwork(thumbnail=Thumbnail(width=4000, height=1000))
        tall = _artwork(thumbnail=Thumbnail(width=1000, height=4000))
        assert aspect_ratio_signal(wide, 1.0) == pytest.approx(aspect_ratio_signal(tall, 1.0))

    def test_resolution_stops_helping_past_the_ceiling(self):
        # Both dimensions scale, so the aspect signal is held constant and only the
        # resolution signal differs between the two.
        at = _artwork(
            thumbnail=Thumbnail(
                width=RESOLUTION_CEILING, height=RESOLUTION_CEILING // 2, alt_text="x"
            )
        )
        beyond = _artwork(
            thumbnail=Thumbnail(
                width=RESOLUTION_CEILING * 3, height=RESOLUTION_CEILING * 3 // 2, alt_text="x"
            )
        )
        assert score(at) == pytest.approx(score(beyond))


class TestExplain:
    def test_breakdown_totals_match_the_score(self):
        artwork = _artwork()
        assert explain(artwork).total == pytest.approx(score(artwork))

    def test_breakdown_names_every_weight(self):
        breakdown = explain(_artwork())
        assert set(breakdown.contributions) == set(WEIGHTS)
        rendered = breakdown.format()
        for name in WEIGHTS:
            assert name in rendered
