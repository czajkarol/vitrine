"""What earns a place in the local index.

Pure. The index is a cache of AIC's collection, and these are the rules for what is worth
caching — applied once at index time so the display path never has to think about it.
"""

from typing import Final

from app.domain.artwork import PREFERRED_IIIF_WIDTH, Artwork

# The display asks IIIF for `PREFERRED_IIIF_WIDTH` pixels. A source narrower than that is
# upscaled by the image server and arrives soft, which on a full-bleed ambient display is
# the most visible possible defect. Works whose dimensions AIC does not report are kept:
# an unknown size is not evidence of a bad one, and the display already handles an image
# that turns out to be unusable.
MIN_LONGEST_SIDE: Final[int] = PREFERRED_IIIF_WIDTH


def source_longest_side(artwork: Artwork) -> int | None:
    """The longer edge of the original, or None when AIC did not say."""
    thumbnail = artwork.thumbnail
    if thumbnail is None or thumbnail.width is None or thumbnail.height is None:
        return None
    return max(thumbnail.width, thumbnail.height)


def is_indexable(artwork: Artwork) -> bool:
    """Whether this artwork belongs in the index.

    Public domain and a usable image are non-negotiable (ADR-0007); the size floor is a
    quality judgement and is deliberately forgiving about missing data.
    """
    if not artwork.is_displayable:
        return False
    longest = source_longest_side(artwork)
    if longest is None:
        return True
    return longest >= MIN_LONGEST_SIDE
