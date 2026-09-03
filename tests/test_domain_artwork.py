"""Unit tests for the domain layer. Pure functions, no mocks, no I/O."""

import pytest

from app.domain.artwork import Artwork, ArtworkPage, Thumbnail, iiif_url


def make(**overrides) -> Artwork:
    base = {"id": 1, "title": "A work", "is_public_domain": True, "image_id": "abc"}
    return Artwork(**{**base, **overrides})


class TestIsDisplayable:
    def test_public_domain_with_image_is_displayable(self):
        assert make().is_displayable

    def test_non_public_domain_is_never_displayable(self):
        # ADR-0007: a hard filter, not a preference. Even with a perfectly good image.
        assert not make(is_public_domain=False).is_displayable

    def test_missing_image_id_is_not_displayable(self):
        assert not make(image_id=None).is_displayable

    def test_empty_image_id_is_not_displayable(self):
        assert not make(image_id="").is_displayable


class TestArtworkPage:
    def test_displayable_filters_out_ineligible_works(self):
        page = ArtworkPage(
            artworks=(
                make(id=1),
                make(id=2, is_public_domain=False),
                make(id=3, image_id=None),
                make(id=4),
            ),
            iiif_base="https://www.artic.edu/iiif/2",
        )
        assert [a.id for a in page.displayable()] == [1, 4]

    def test_empty_page_yields_nothing(self):
        page = ArtworkPage(iiif_base="https://www.artic.edu/iiif/2")
        assert page.displayable() == ()


class TestIiifUrl:
    def test_builds_a_url_at_a_cached_width(self):
        assert iiif_url("https://www.artic.edu/iiif/2", "abc", 843) == (
            "https://www.artic.edu/iiif/2/abc/full/843,/0/default.jpg"
        )

    def test_tolerates_a_trailing_slash_on_the_base(self):
        assert iiif_url("https://www.artic.edu/iiif/2/", "abc", 843).count("//") == 1

    @pytest.mark.parametrize("width", [123, 1000, 2000, 0])
    def test_rejects_widths_off_the_cached_ladder(self, width):
        # An uncached width means an edge-cache miss and a slow first paint.
        with pytest.raises(ValueError, match="cached IIIF width"):
            iiif_url("https://www.artic.edu/iiif/2", "abc", width)


class TestParsingNulls:
    def test_null_strings_become_none(self):
        # AIC returns null, not "", for absent strings.
        artwork = Artwork.model_validate(
            {"id": 1, "title": "t", "artist_title": None, "description": None}
        )
        assert artwork.artist_title is None
        assert artwork.description is None

    def test_thumbnail_may_be_absent_entirely(self):
        assert make(thumbnail=None).thumbnail is None

    def test_thumbnail_fields_are_individually_optional(self):
        thumb = Thumbnail.model_validate({"lqip": "data:image/gif;base64,AA", "width": 100})
        assert thumb.height is None
        assert thumb.alt_text is None
