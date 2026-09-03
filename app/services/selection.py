"""Choosing and delivering the next artwork.

This is the orchestration ADR-0003 describes: read from the local index, fall back to AIC
only when there is no index, and fall back again to a bundled set when there is no network
either. The rule for *which* artwork wins is in `domain/selection.py`, where it is pure.
"""

import logging
import random
from dataclasses import dataclass
from typing import Final

from app.domain.artwork import Artwork
from app.domain.selection import choose_next
from app.providers.aic.client import AicClient, AicError
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.history import HistoryRepository
from app.repositories.preferences import PreferencesRepository
from app.services.fallback import FallbackSet

logger = logging.getLogger(__name__)

# How many rows to pull before applying the history penalty. Large enough that the penalty
# has something to choose between, small enough to stay a trivial query.
CANDIDATE_POOL: Final[int] = 60

# The IIIF base is a property of AIC's deployment and must never be hardcoded (CLAUDE.md).
# It arrives on every API response, so we remember the last one we were told and reuse it
# for artworks that came out of the index, which carries no response of its own.
IIIF_BASE_KEY: Final[str] = "iiif_base"


@dataclass(frozen=True)
class Selection:
    """One artwork, plus which tier produced it."""

    artwork: Artwork
    iiif_base: str
    source: str  # "index" | "aic" | "fallback"


class SelectionService:
    def __init__(
        self,
        index: ArtworkIndexRepository,
        history: HistoryRepository,
        preferences: PreferencesRepository,
        fallback: FallbackSet,
        client: AicClient | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._index = index
        self._history = history
        self._preferences = preferences
        self._fallback = fallback
        self._client = client
        self._rng = rng or random.Random()

    async def next_artwork(self) -> Selection | None:
        """The next artwork to show, from the first tier that can produce one."""
        selection = await self._from_index()
        if selection is None:
            selection = await self._from_aic()
        if selection is None:
            selection = await self._from_fallback()
        if selection is not None:
            await self._history.push(selection.artwork.id)
        return selection

    async def _known_iiif_base(self) -> str | None:
        """The last base AIC told us, or the one recorded with the bundled set."""
        stored = await self._preferences.get(IIIF_BASE_KEY)
        return stored or self._fallback.iiif_base

    async def _from_index(self) -> Selection | None:
        candidates = await self._index.sample(CANDIDATE_POOL)
        if not candidates:
            return None
        iiif_base = await self._known_iiif_base()
        if iiif_base is None:
            # We hold artworks but no way to build an image URL. Let a live AIC response
            # teach us one rather than guessing.
            logger.warning("Index has rows but no IIIF base is known yet")
            return None
        recent = await self._history.recent()
        artwork = choose_next(candidates, [a.id for a in candidates], recent, self._rng)
        return Selection(artwork=artwork, iiif_base=iiif_base, source="index")

    async def _from_aic(self) -> Selection | None:
        """No index yet. ADR-0003 calls this the fallback, not the design."""
        if self._client is None:
            return None
        try:
            result = await self._client.random_displayable()
        except AicError as exc:
            logger.warning("AIC unavailable while selecting an artwork: %s", exc)
            return None
        if result is None:
            return None
        artwork, iiif_base = result
        # Remember it, so an index-sourced artwork can be shown next time even offline.
        await self._preferences.set(IIIF_BASE_KEY, iiif_base)
        return Selection(artwork=artwork, iiif_base=iiif_base, source="aic")

    async def _from_fallback(self) -> Selection | None:
        """No index and no reachable API. Something must still appear on screen."""
        artwork = self._fallback.random(self._rng)
        iiif_base = await self._known_iiif_base()
        if artwork is None or iiif_base is None:
            return None
        logger.info("Serving artwork %s from the bundled fallback set", artwork.id)
        return Selection(artwork=artwork, iiif_base=iiif_base, source="fallback")
