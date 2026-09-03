"""Choosing and delivering the next artwork.

This is the orchestration ADR-0003 describes: read from the local index, fall back to AIC
only when there is no index, and fall back again to a bundled set when there is no network
either. The rule for *which* artwork wins is in `domain/selection.py`, where it is pure.
"""

import logging
import random
from dataclasses import dataclass
from typing import Final

from app.domain.affinity import AffinityProfile, build_profile, personal_score
from app.domain.artwork import Artwork
from app.domain.selection import choose_next
from app.providers.aic.client import AicClient, AicError
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.feedback import FeedbackRepository
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

# How many of the personally-ranked candidates to keep before the history penalty picks.
# A floor rather than the whole answer — see `_rank_personally`.
PERSONAL_SHORTLIST: Final[int] = 12


@dataclass(frozen=True)
class SelectionQuery:
    """What the display asked for. Defaults are the plain random rotation.

    Filters are canonical facet keys (`style.japanese`, `type.print`) rather than AIC's own
    values — see `domain/vocabulary.py` and ADR-0009. `facets` are ANDed and hold at most
    one per group, which is the product-spec's reasoning about radios: "landscape AND
    portraits" narrows to nothing. `exclude` has no such limit, because excluding several
    things at once is ordinary and does not collapse the result set.
    """

    mode: str = "random"
    """`random`, `curated` or `personal`. Personal ranks over curated rather than
    replacing it — see `domain/affinity.py` and ADR-0010."""

    facets: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @property
    def curated(self) -> bool:
        """Whether the index should be sampled from its scored rows.

        True for the personal mode as well: personal ranking multiplies the curated score,
        so it wants the same pool to work from.
        """
        return self.mode in ("curated", "personal")

    @property
    def is_filtered(self) -> bool:
        """Whether anything narrows the corpus.

        Curated is not in this list on purpose: it changes the ordering, not the set, so a
        curated request can still be answered by a tier that cannot rank. An exclusion is,
        because a tier that cannot honour it would show the very thing that was excluded.
        """
        return bool(self.facets or self.exclude)


@dataclass(frozen=True)
class Selection:
    """One artwork, plus which tier produced it."""

    artwork: Artwork
    iiif_base: str
    source: str  # "index" | "aic" | "fallback"

    personalised: bool = False
    """Whether the personal mode actually personalised this, or fell back to curated
    ranking for want of enough likes. The display says which, because a recommendation
    that is not one is worse than no recommendation."""


class SelectionService:
    def __init__(
        self,
        index: ArtworkIndexRepository,
        history: HistoryRepository,
        preferences: PreferencesRepository,
        fallback: FallbackSet,
        client: AicClient | None = None,
        rng: random.Random | None = None,
        feedback: FeedbackRepository | None = None,
    ) -> None:
        self._index = index
        self._history = history
        self._preferences = preferences
        self._fallback = fallback
        self._client = client
        self._rng = rng or random.Random()
        self._feedback = feedback

    async def _hidden(self) -> list[int]:
        """Artworks the user has hidden, excluded in every mode. `X` is not a preference
        about ordering, and a mode switch is not a change of mind about it."""
        return await self._feedback.ids("hide") if self._feedback else []

    async def profile(self) -> AffinityProfile:
        """The affinity profile, rebuilt from the likes as they stand.

        Not cached. It changes with every like, the query is two indexed lookups against a
        table with tens of rows in it, and a cache here would be a staleness bug waiting
        for someone to like something and not see the effect.
        """
        if self._feedback is None:
            return AffinityProfile()
        liked = await self._feedback.facets_of_liked()
        return build_profile(liked.values())

    async def next_artwork(self, query: SelectionQuery | None = None) -> Selection | None:
        """The next artwork to show, from the first tier that can produce one."""
        query = query or SelectionQuery()
        selection = await self._from_index(query)
        # A *filtered* request is answerable only from the index — AIC and the bundled set
        # cannot honour the filter, so silently ignoring it would be worse than failing.
        # Curated is not a filter and does not constrain: see `_from_index`.
        constrained = query.is_filtered
        if selection is None and not constrained:
            selection = await self._from_aic()
        if selection is None and not constrained:
            selection = await self._from_fallback()
        if selection is not None:
            await self._history.push(selection.artwork.id)
        return selection

    async def _known_iiif_base(self) -> str | None:
        """The last base AIC told us, or the one recorded with the bundled set."""
        stored = await self._preferences.get(IIIF_BASE_KEY)
        return stored or self._fallback.iiif_base

    async def _from_index(self, query: SelectionQuery) -> Selection | None:
        hidden = await self._hidden()
        candidates = await self._index.sample(
            CANDIDATE_POOL,
            curated=query.curated,
            facets=query.facets,
            exclude=query.exclude,
            hidden=hidden,
        )
        if not candidates and query.curated:
            # Curated is a preference about *ordering*, not an exclusion. If nothing has
            # been scored yet, an unranked artwork is still one the user wants to see —
            # unlike a type filter, where showing the wrong thing is worse than showing
            # nothing. Better a rotation than a blank screen with a puzzling message.
            logger.info("Nothing scored yet; serving %s unranked", query)
            candidates = await self._index.sample(
                CANDIDATE_POOL,
                curated=False,
                facets=query.facets,
                exclude=query.exclude,
                hidden=hidden,
            )
        if not candidates and query.is_filtered:
            # A filter that matches nothing must not silently become "anything". Falling
            # through to AIC here would show a work the user explicitly filtered out.
            logger.info("No indexed artwork matches %s", query)
            return None
        if not candidates:
            return None
        iiif_base = await self._known_iiif_base()
        if iiif_base is None:
            # We hold artworks but no way to build an image URL. Let a live AIC response
            # teach us one rather than guessing.
            logger.warning("Index has rows but no IIIF base is known yet")
            return None
        recent = await self._history.recent()
        personalised = False
        if query.mode == "personal":
            candidates, personalised = await self._rank_personally(candidates)
        artwork = choose_next(candidates, [a.id for a in candidates], recent, self._rng)
        return Selection(
            artwork=artwork,
            iiif_base=iiif_base,
            source="index",
            personalised=personalised,
        )

    async def _rank_personally(self, candidates: list[Artwork]) -> tuple[list[Artwork], bool]:
        """Narrow the pool to what best matches the profile, or leave it alone.

        Ranking happens here, in Python, rather than in the sampling query: the profile
        changes with every like and lives in `domain/`, and a SQL expression carrying it
        would have to be rebuilt on every request and could not be explained.

        Below the cold-start threshold this returns the pool untouched and says so, so the
        caller can tell the user it is showing curated picks rather than theirs. A
        recommendation drawn from two likes is not a recommendation.
        """
        profile = await self.profile()
        if not profile.is_usable:
            return candidates, False

        facets, scores = await self._index.facets_and_scores([a.id for a in candidates])
        ranked = sorted(
            candidates,
            key=lambda artwork: personal_score(
                scores.get(artwork.id), profile, facets.get(artwork.id, ())
            ),
            reverse=True,
        )
        # The best third, not the single best: the history penalty still has to have
        # something to choose between, and an ambient display that shows the same
        # top-ranked artwork every time is not one anybody would leave running.
        keep = max(PERSONAL_SHORTLIST, len(ranked) // 3)
        return ranked[:keep], True

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
