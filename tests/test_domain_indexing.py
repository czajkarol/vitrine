"""What earns a place in the index."""

from app.domain.artwork import Artwork, Thumbnail
from app.domain.indexing import MIN_LONGEST_SIDE, is_indexable, source_longest_side


def _artwork(**overrides) -> Artwork:
    base = {
        "id": 1,
        "title": "A work",
        "image_id": "abc",
        "is_public_domain": True,
        "thumbnail": Thumbnail(width=2000, height=1500),
    }
    return Artwork(**{**base, **overrides})


class TestIsIndexable:
    def test_accepts_a_large_public_domain_work_with_an_image(self):
        assert is_indexable(_artwork())

    def test_rejects_anything_not_public_domain(self):
        # ADR-0007 makes this a hard filter, not a preference.
        assert not is_indexable(_artwork(is_public_domain=False))

    def test_rejects_a_work_with_no_image(self):
        assert not is_indexable(_artwork(image_id=None))

    def test_rejects_a_source_smaller_than_the_display_width(self):
        small = MIN_LONGEST_SIDE - 1
        assert not is_indexable(_artwork(thumbnail=Thumbnail(width=small, height=small)))

    def test_accepts_a_source_exactly_at_the_floor(self):
        assert is_indexable(_artwork(thumbnail=Thumbnail(width=MIN_LONGEST_SIDE, height=100)))

    def test_keeps_a_work_whose_dimensions_are_unknown(self):
        # An unreported size is not evidence of a bad one, and the display already
        # handles an image that turns out to be unusable.
        assert is_indexable(_artwork(thumbnail=None))
        assert is_indexable(_artwork(thumbnail=Thumbnail(width=None, height=None)))


class TestSourceLongestSide:
    def test_uses_the_longer_edge(self):
        assert source_longest_side(_artwork(thumbnail=Thumbnail(width=100, height=900))) == 900

    def test_is_none_when_unreported(self):
        assert source_longest_side(_artwork(thumbnail=None)) is None
