"""Artwork domain models and the rules for whether a work can be displayed.

Pure. No I/O, no httpx, no knowledge of AIC's JSON shape — `providers/aic/` owns that and
hands these models over already built.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict

# The IIIF widths AIC keeps cached. Requesting anything else is an edge-cache miss and a
# slow first paint, so both the frontend and the image proxy are limited to this ladder.
# 1686 is offered for public-domain works specifically.
CACHED_IIIF_WIDTHS: Final[tuple[int, ...]] = (200, 400, 600, 843, 1686)
PREFERRED_IIIF_WIDTH: Final[int] = 843


class Thumbnail(BaseModel):
    """The inline thumbnail block. Absent entirely on works with no image."""

    model_config = ConfigDict(frozen=True)

    lqip: str | None = None
    """Base64 GIF blur placeholder, inline in the response. Paint it while the real
    image decodes."""

    width: int | None = None
    height: int | None = None

    alt_text: str | None = None
    """Written by the museum. Used for `alt=` and, later, to ground AI prompts."""


class Color(BaseModel):
    """Dominant colour, as HSL plus how much of the image it covers."""

    model_config = ConfigDict(frozen=True)

    h: int
    s: int
    l: int  # noqa: E741 — AIC's field name; renaming it here would obscure the mapping.
    population: int | None = None
    percentage: float | None = None


class Artwork(BaseModel):
    """One artwork, as the rest of the application understands it."""

    model_config = ConfigDict(frozen=True)

    id: int
    title: str

    artist_title: str | None = None
    artist_display: str | None = None
    date_display: str | None = None
    medium_display: str | None = None
    credit_line: str | None = None
    department_title: str | None = None
    place_of_origin: str | None = None
    artwork_type_title: str | None = None
    main_reference_number: str | None = None

    description: str | None = None
    """CC BY 4.0, unlike everything else here. Showing it obliges us to attribute AIC."""

    image_id: str | None = None
    is_public_domain: bool = False
    is_boosted: bool = False

    thumbnail: Thumbnail | None = None
    color: Color | None = None

    @property
    def is_displayable(self) -> bool:
        """Whether this work may be put on screen.

        Two conditions, both hard. Public domain is a non-negotiable constraint, not a
        preference (ADR-0007). An image id is simply required to build a IIIF URL, and it
        is missing on roughly 55% of the collection.
        """
        return self.is_public_domain and bool(self.image_id)


class ArtworkPage(BaseModel):
    """A batch of artworks together with the IIIF base that came back with them.

    `config.iiif_url` is returned on every AIC response and must never be hardcoded, so it
    travels with the records rather than being looked up separately.
    """

    model_config = ConfigDict(frozen=True)

    artworks: tuple[Artwork, ...] = ()
    iiif_base: str

    total: int | None = None
    """How many records match in total. Present on listing responses; the crawler uses it
    to know when it has reached the end."""

    total_pages: int | None = None
    current_page: int | None = None

    def displayable(self) -> tuple[Artwork, ...]:
        """The subset that passes the public-domain and image checks."""
        return tuple(a for a in self.artworks if a.is_displayable)


def iiif_url(iiif_base: str, image_id: str, width: int = PREFERRED_IIIF_WIDTH) -> str:
    """Build a IIIF Image API 2.0 URL at one of the cached widths.

    Raises `ValueError` for a width off the ladder rather than silently fetching an
    uncached size.
    """
    if width not in CACHED_IIIF_WIDTHS:
        raise ValueError(f"width {width} is not a cached IIIF width {CACHED_IIIF_WIDTHS}")
    return f"{iiif_base.rstrip('/')}/{image_id}/full/{width},/0/default.jpg"
