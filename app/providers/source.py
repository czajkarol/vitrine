"""The `ArtworkSource` boundary, with a second implementation behind it at last.

`docs/architecture.md` has named this interface since M0 and only `providers/aic/` sat
under it, which is the usual state of a Protocol with one implementation: untested as a
boundary. ADR-0012 wrote down what a second source would cost and recommended against
paying it; ADR-0013 records the owner's decision to pay a deliberately small part of it.

**This is the interface for a *live* source, and that is the whole reason it is small.**
The Art Institute does not implement it: AIC is indexed, scored, faceted and served out of
SQLite, and everything about that — `SelectionService`, `ArtworkIndexRepository`,
`domain/vocabulary.py` — is a much larger surface than any second museum is going to be
worth. A live source answers two questions instead: give me one artwork, and what may I
filter on. Nothing here knows about scoring, history, facets or the index.

The exchange type is `SourceArtwork` rather than a bare `Artwork`, because the one thing
the two museums genuinely disagree about is how an image URL is built. AIC hands out a
IIIF base and an id; Cleveland hands out finished URLs. So the source says which it has,
and the display does the corresponding thing.
"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.artwork import Artwork


class SourceError(RuntimeError):
    """The museum could not be reached, or answered with something unusable.

    One error type rather than a hierarchy: a live source has exactly one recovery, which
    is to say so quietly and leave the previous artwork on screen.
    """


@dataclass(frozen=True)
class SourceArtwork:
    """One artwork from a live source, with whatever it takes to show its image.

    Exactly one of `iiif_base` and `image_url` is meaningful. `iiif_base` means the browser
    picks a width off the cached ladder and can fall back to the proxy (ADR-0008);
    `image_url` means the source has already decided, and there is nothing to choose.
    """

    artwork: Artwork
    iiif_base: str = ""
    image_url: str | None = None


@dataclass(frozen=True)
class SourceFilter:
    """One filter a live source offers, and how many artworks sit behind it.

    The same shape as an indexed facet option, so the panel renders both with one path —
    but the value is the museum's own vocabulary rather than a canonical facet key. Folding
    a second museum's terms into `domain/vocabulary.py` is item 6 of ADR-0012's eight, and
    it is deliberately not being done here.
    """

    value: str
    label: str
    count: int


class ArtworkSource(Protocol):
    """A museum served live, with no index behind it."""

    key: str
    """Short identifier: `cma`. Stored with a favourite, sent on the artwork, and part of
    what makes artwork id 1 unambiguous across two museums (migration 010)."""

    async def random(self, artwork_type: str | None = None) -> SourceArtwork | None:
        """One displayable artwork, optionally of one type. None when there are none."""
        ...

    async def get(self, artwork_id: int) -> SourceArtwork | None:
        """One artwork by id, for anything that names one after the fact."""
        ...

    async def artwork_types(self) -> list[SourceFilter]:
        """What may be filtered on, with counts. May be empty."""
        ...

    async def aclose(self) -> None:
        """Release the HTTP client. Called once, at shutdown."""
        ...
