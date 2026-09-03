"""The bundled artwork set, for a fresh clone with no index and no network.

The records are real AIC responses captured once and committed, not hand-written — the
same rule the test fixtures follow, and for the same reason. The images themselves are not
bundled: they still come from AIC, so this covers "no index" and "AIC's API is down", not
"no internet at all". Bundling ~30 images would make the repository a partial mirror of the
collection, which ADR-0007 exists partly to avoid.
"""

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.domain.artwork import Artwork

logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data" / "fallback_artworks.json"
)


@dataclass(frozen=True)
class FallbackSet:
    artworks: tuple[Artwork, ...] = ()
    iiif_base: str | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> "FallbackSet":
        """Read the bundled set. A missing or unreadable file is not fatal."""
        source = path or DEFAULT_FALLBACK_PATH
        if not source.is_file():
            logger.warning("No bundled fallback set at %s", source)
            return cls()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
            artworks = tuple(Artwork.model_validate(r) for r in payload.get("artworks", []))
        except (OSError, ValueError) as exc:
            # A corrupt bundled file must not stop the app booting; it just means this
            # tier has nothing to offer.
            logger.error("Bundled fallback set at %s is unusable: %s", source, exc)
            return cls()
        return cls(artworks=artworks, iiif_base=payload.get("iiif_base"))

    def random(self, rng: random.Random) -> Artwork | None:
        displayable = [a for a in self.artworks if a.is_displayable]
        return rng.choice(displayable) if displayable else None

    def get(self, artwork_id: int) -> Artwork | None:
        """Look one up by id.

        Needed because a request that names an artwork — an interpretation, say — has to
        find the metadata for whichever tier put it on screen, and on a fresh clone with
        no network that tier is this one.
        """
        return next((a for a in self.artworks if a.id == artwork_id), None)
