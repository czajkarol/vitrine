"""HTTP response shapes. Serialisation only — no logic lives here."""

from typing import Literal

from pydantic import BaseModel, Field

from app.domain.artwork import Artwork


class ArtworkResponse(BaseModel):
    """One artwork, shaped for the display.

    The IIIF base and the image id are sent separately rather than as a finished URL:
    only the browser knows its viewport and pixel ratio, so only the browser can pick the
    width. See `docs/architecture.md`.
    """

    id: int
    title: str
    artist: str | None
    artist_display: str | None
    date_display: str | None
    medium_display: str | None
    credit_line: str | None
    place_of_origin: str | None
    main_reference_number: str | None

    description: str | None
    """CC BY 4.0. If this is shown, AIC must be attributed alongside it."""

    iiif_base: str
    image_id: str
    lqip: str | None
    alt_text: str | None
    source_width: int | None
    source_height: int | None
    color: dict[str, float] | None
    is_boosted: bool

    source: str = "aic"
    """Which tier produced this: index, aic, or fallback. The display shows a quiet
    offline indicator when it is not the live API."""

    @classmethod
    def from_domain(
        cls, artwork: Artwork, iiif_base: str, source: str = "aic"
    ) -> "ArtworkResponse":
        if artwork.image_id is None:  # pragma: no cover — guarded by is_displayable
            raise ValueError("artwork has no image_id and should not have been selected")
        thumbnail = artwork.thumbnail
        colour = artwork.color
        return cls(
            id=artwork.id,
            title=artwork.title,
            artist=artwork.artist_title,
            artist_display=artwork.artist_display,
            date_display=artwork.date_display,
            medium_display=artwork.medium_display,
            credit_line=artwork.credit_line,
            place_of_origin=artwork.place_of_origin,
            main_reference_number=artwork.main_reference_number,
            description=artwork.description,
            iiif_base=iiif_base,
            image_id=artwork.image_id,
            lqip=thumbnail.lqip if thumbnail else None,
            alt_text=thumbnail.alt_text if thumbnail else None,
            source_width=thumbnail.width if thumbnail else None,
            source_height=thumbnail.height if thumbnail else None,
            color=({"h": colour.h, "s": colour.s, "l": colour.l} if colour is not None else None),
            is_boosted=artwork.is_boosted,
            source=source,
        )


class ErrorResponse(BaseModel):
    """A machine-readable failure. `code` is what the frontend keys its message off."""

    code: str
    detail: str


class PreferencesResponse(BaseModel):
    """The preferences the user can actually set.

    A typed shape rather than a free key/value passthrough: the `preferences` table also
    holds things the app learned for itself — the IIIF base, the crawler's progress — and
    those are not the browser's to write.
    """

    interval_minutes: Literal[1, 5, 15, 30] = 5
    mode: Literal["random", "curated"] = "random"
    artwork_type: str | None = Field(default=None, max_length=100)
    # Only the languages frontend/locales/ actually has strings for. The default is
    # overridden by `default_language` when nothing has been saved yet.
    language: Literal["en", "pl"] = "en"


class FilterOption(BaseModel):
    """One Explore filter, with the number of artworks actually behind it."""

    value: str
    count: int


class FiltersResponse(BaseModel):
    """The filters worth offering, biggest first.

    Only options the local index can sustain appear here: a filter yielding four
    artworks is worse than no filter (docs/product-spec.md). The counts are real, from
    the index, not from a hardcoded list that would drift from what the API supports.
    """

    artwork_types: list[FilterOption] = []
    minimum_count: int
    indexed_total: int
