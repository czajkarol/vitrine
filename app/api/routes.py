"""HTTP routes. Shapes in, shapes out — orchestration belongs below this layer."""

import logging
import re
from time import monotonic
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError

from app.api.schemas import (
    MAX_EXCLUSIONS,
    MAX_INCLUSIONS,
    AicStats,
    AiKeyRequest,
    AiKeyResponse,
    AiStatus,
    ArtworkResponse,
    CacheStats,
    FeedbackItem,
    FeedbackRequest,
    FeedbackSummary,
    FilterOption,
    FiltersResponse,
    HealthResponse,
    InterpretationResponse,
    PreferencesResponse,
    ProviderStats,
    ScoringResponse,
    ScoringWeight,
    StatsResponse,
    UsageStats,
    VisualDescriptionResponse,
)
from app.core.config import Settings
from app.domain.affinity import MIN_LIKES_FOR_PROFILE
from app.domain.artwork import CACHED_IIIF_WIDTHS, PREFERRED_IIIF_WIDTH
from app.domain.rate_limit import RateLimiter
from app.domain.scoring import WEIGHTS
from app.domain.vocabulary import FACET_GROUPS, FacetGroup, facet_for, label_for
from app.providers.ai.base import AiError
from app.providers.aic.client import AicClient, AicError, AicUnavailableError
from app.providers.source import SourceError
from app.repositories.ai_usage import AiUsageRepository, today
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.credentials import CredentialStoreError
from app.repositories.feedback import FeedbackRepository
from app.repositories.preferences import PreferencesRepository
from app.services.ai_credentials import AiCredentialService, AiKeyStatus
from app.services.interpretation import (
    ArtworkNotFoundError,
    BudgetExhaustedError,
    CircuitOpenError,
    DescriptionUnsupportedError,
    InterpretationService,
    NotDescribableError,
)
from app.services.selection import SelectionQuery, SelectionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# AIC image ids are UUIDs. Validating the shape keeps /image from being coaxed into
# fetching something that is not an image id.
IMAGE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def get_client(request: Request) -> AicClient:
    client: AicClient = request.app.state.aic_client
    return client


def get_selection(request: Request) -> SelectionService:
    service: SelectionService = request.app.state.selection
    return service


def get_preferences(request: Request) -> PreferencesRepository:
    return PreferencesRepository(request.app.state.database)


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_interpretation(request: Request) -> InterpretationService:
    service: InterpretationService = request.app.state.interpretation
    return service


def get_index(request: Request) -> ArtworkIndexRepository:
    return ArtworkIndexRepository(request.app.state.database)


def get_usage(request: Request) -> AiUsageRepository:
    return AiUsageRepository(request.app.state.database)


def get_ai_credentials(request: Request) -> AiCredentialService:
    service: AiCredentialService = request.app.state.ai_credentials
    return service


def _rate_limit(request: Request, *, dependent: bool) -> None:
    """Spend one token, or refuse with a `Retry-After` the caller can actually wait out.

    A dependency and not middleware, so that it applies to exactly the two routes whose
    cost leaves the machine. Limiting `/api/preferences` or `/api/health` would bound
    nothing and would make the settings panel feel broken under a burst.

    The refusal carries the same `detail` shape as every other error here, because the
    frontend keys its message off `detail` and a 429 is not special enough to be the one
    exception.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    decision = limiter.check(dependent=dependent)
    if decision.allowed:
        return
    logger.info(
        "Rate limit refused %s; retry after %ds.", request.url.path, decision.retry_after_seconds
    )
    raise HTTPException(
        status_code=429,
        detail="too_many_requests",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def get_feedback(request: Request) -> FeedbackRepository:
    return FeedbackRepository(request.app.state.database)


def enforce_rate_limit(request: Request) -> None:
    """An advance. Spends a token and grants the credit its image will use."""
    _rate_limit(request, dependent=False)


def enforce_dependent_rate_limit(request: Request) -> None:
    """The image for an artwork already served — the second half of one advance.

    Spends the credit that advance granted rather than a token of its own. Without this
    the limiter caused the storm it exists to prevent: an `<img>` cannot see a `429`, so
    the display read a refused image as a dead one, dropped the artwork and asked for
    another immediately. Seen in a browser, and it did not recover on its own.

    A proxy call with no advance behind it still pays full price, so this is not a way
    around the limit.
    """
    _rate_limit(request, dependent=True)


RateLimited = Depends(enforce_rate_limit)
DependentRateLimited = Depends(enforce_dependent_rate_limit)


ClientDep = Annotated[AicClient, Depends(get_client)]
SelectionDep = Annotated[SelectionService, Depends(get_selection)]
PreferencesDep = Annotated[PreferencesRepository, Depends(get_preferences)]
IndexDep = Annotated[ArtworkIndexRepository, Depends(get_index)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
InterpretationDep = Annotated[InterpretationService, Depends(get_interpretation)]
AiCredentialsDep = Annotated[AiCredentialService, Depends(get_ai_credentials)]
UsageDep = Annotated[AiUsageRepository, Depends(get_usage)]
FeedbackDep = Annotated[FeedbackRepository, Depends(get_feedback)]

# Below this, a filter cannot sustain a rotation and is not offered at all.
MIN_FILTER_COUNT: Final[int] = 40

# And above this many options, a list stops being a menu. Applies to style and subject;
# artwork type is a closed vocabulary of 30 facets and all of it is offered.
#
# Raised from 30 with M10, to the owner's "keep it broad". The canonical layer changed what
# this number is cutting off: it used to hide values that were duplicates of ones already
# on the list — `portraits` under `portrait` — and now every option is a distinct thing.
# 82 styles and 173 subjects clear MIN_FILTER_COUNT, so this still cuts, and the count
# beside each option is what makes a long list navigable rather than the length itself.
MAX_FILTER_OPTIONS: Final[int] = 60

INTERVAL_KEY: Final[str] = "interval_seconds"
MODE_KEY: Final[str] = "mode"
ARTWORK_TYPE_KEY: Final[str] = "artwork_type"
STYLE_KEY: Final[str] = "style"
SUBJECT_KEY: Final[str] = "subject"
EXCLUDE_KEY: Final[str] = "exclude"
LANGUAGE_KEY: Final[str] = "language"
AMBIENT_KEY: Final[str] = "ambient"
AMBIENT_BY_HAND_KEY: Final[str] = "ambient_by_hand"
MUSEUM_KEY: Final[str] = "museum"

# The exclusion list is several values in a table that stores one string per key. Comma
# separated rather than JSON because a facet key is `[a-z0-9.-]` by construction and can
# never contain a comma — see `domain/vocabulary.py` — so the encoding cannot be ambiguous
# and stays readable to anyone who opens the database.
EXCLUDE_SEPARATOR: Final[str] = ","


@router.get("/artwork/random", response_model=ArtworkResponse, dependencies=[RateLimited])
async def random_artwork(
    request: Request,
    selection: SelectionDep,
    feedback: FeedbackDep,
    mode: Annotated[Literal["random", "curated", "personal"], Query()] = "random",
    museum: Annotated[Literal["aic", "cma"], Query()] = "aic",
    artwork_type: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    style: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    subject: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    exclude: Annotated[list[str] | None, Query(max_length=MAX_EXCLUSIONS)] = None,
) -> ArtworkResponse:
    """One random public-domain artwork with a usable image.

    The service decides where it comes from — for the Art Institute, the local index
    first, then AIC, then the bundled set (ADR-0003); for Cleveland, one live call
    (ADR-0013). This route only shapes the answer.

    The three named parameters keep their names for the three groups and carry canonical
    facet keys since M10 — `style=style.japanese`, not `style=Japanese (culture or style)`.
    All four are repeatable since M13: several values inside a group are ORed, the groups
    are ANDed together, and `exclude` is NOT-ed over all of them at once.
    """
    query = SelectionQuery(
        mode=mode,
        museum=museum,
        facets=tuple(tuple(_included_facets(group)) for group in (artwork_type, style, subject)),
        exclude=tuple(_valid_facets(exclude)),
    )
    try:
        result = await selection.next_artwork(query)
    except AicUnavailableError as exc:  # pragma: no cover — the service absorbs these
        logger.warning("AIC unavailable serving /artwork/random: %s", exc)
        raise HTTPException(status_code=503, detail="aic_unavailable") from exc
    except AicError as exc:  # pragma: no cover — the service absorbs these
        logger.error("AIC error serving /artwork/random: %s", exc)
        raise HTTPException(status_code=502, detail="aic_error") from exc

    if result is None:
        if query.is_filtered:
            # A filter that matches nothing is a different situation from the API being
            # down, and the display says something different about it.
            raise HTTPException(status_code=404, detail="no_matching_artwork")
        # Every tier came up empty: no index, no network, no bundled set.
        raise HTTPException(status_code=503, detail="aic_unavailable")

    if result.iiif_base:
        # Remembered so the image proxy never has to guess a IIIF base or hardcode one.
        # A source with no IIIF service leaves the last known one alone rather than
        # clearing it — the proxy is still the fallback for Art Institute images.
        request.app.state.iiif_base = result.iiif_base
    response = ArtworkResponse.from_domain(
        result.artwork,
        result.iiif_base,
        source=result.source,
        museum=result.museum,
        image_url=result.image_url,
    )
    response.personalised = result.personalised
    existing = await feedback.get(result.artwork.id, result.museum)
    response.feedback = existing.kind if existing else None
    response.liked = existing is not None and existing.kind == "like"
    return response


@router.get("/image/{image_id}", dependencies=[DependentRateLimited])
async def image_proxy(
    request: Request,
    client: ClientDep,
    image_id: Annotated[str, Path()],
    w: Annotated[int, Query()] = PREFERRED_IIIF_WIDTH,
) -> Response:
    """Fetch a IIIF image server-side — the ADR-0008 fallback.

    Only reached when the browser's direct attempt failed. Restricted to well-formed image
    ids and the cached width ladder so it cannot be used as a general-purpose proxy.
    """
    if not IMAGE_ID_PATTERN.match(image_id):
        raise HTTPException(status_code=400, detail="malformed_image_id")
    if w not in CACHED_IIIF_WIDTHS:
        raise HTTPException(status_code=400, detail="unsupported_width")

    iiif_base: str | None = getattr(request.app.state, "iiif_base", None)
    if not iiif_base:
        raise HTTPException(status_code=503, detail="iiif_base_unknown")

    try:
        upstream = await client.fetch_image(iiif_base, image_id, w)
    except AicError as exc:
        # Covers transport failures too: the client converts httpx errors to AicError so
        # that no httpx exception type is named above providers/.
        logger.warning("image proxy failed for %s: %s", image_id, exc)
        raise HTTPException(status_code=502, detail="image_unavailable") from exc

    if upstream.status_code != 200:
        logger.warning("image proxy upstream %d for %s", upstream.status_code, image_id)
        raise HTTPException(status_code=502, detail="image_unavailable")

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "image/jpeg"),
        # Immutable for a given id and width; caching spares AIC the repeat fetch.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/filters", response_model=FiltersResponse)
async def read_filters(
    request: Request,
    index: IndexDep,
    museum: Annotated[Literal["aic", "cma"], Query()] = "aic",
    artwork_type: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    style: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    subject: Annotated[list[str] | None, Query(max_length=MAX_INCLUSIONS)] = None,
    exclude: Annotated[list[str] | None, Query(max_length=MAX_EXCLUSIONS)] = None,
) -> FiltersResponse:
    """The Explore vocabulary, built from the index rather than a hardcoded list.

    Canonical facets since M10, all three groups out of one table — see ADR-0009.

    **Two different counts, and the difference matters.** What is *offered at all* is
    decided once, unconstrained, against `MIN_FILTER_COUNT`: a filter the index cannot
    sustain is not a filter whatever else is selected, and re-deciding that under the
    current selection would make options appear and vanish as the user clicks. What is
    *shown beside each option* is the constrained count — leave-one-out, so each group is
    counted under the other groups' choices but not its own. Choosing a style updates the
    subject and type counts; the style list the user is standing in does not collapse
    around their own choice.

    An option whose constrained count is zero stays, at zero, and the panel disables it.
    A list that reshuffles under the cursor is worse than a greyed row.

    Cleveland is not indexed and has none of this. Its filters come from its own source and
    are a different, much smaller thing — one closed list of artwork types with live totals.
    ADR-0013.
    """
    if museum != "aic":
        return await _live_filters(request, museum)

    chosen: dict[str, list[str]] = {
        "type": _included_facets(artwork_type),
        "style": _included_facets(style),
        "subject": _included_facets(subject),
    }
    excluded = _valid_facets(exclude)
    labels = await _facet_labels(index)

    groups = {}
    for group in FACET_GROUPS:
        # Leave-one-out: every group's selection except this one's.
        others = [values for key, values in chosen.items() if key != group and values]
        groups[group] = (
            await index.facet_counts(group),
            await index.facet_counts(group, include=others, exclude=excluded),
            labels,
        )

    return FiltersResponse(
        museum="aic",
        artwork_types=_options(*groups["type"]),
        styles=_options(*groups["style"], limit=MAX_FILTER_OPTIONS),
        subjects=_options(*groups["subject"], limit=MAX_FILTER_OPTIONS),
        minimum_count=MIN_FILTER_COUNT,
        maximum_options=MAX_FILTER_OPTIONS,
        indexed_total=await index.count(),
    )


async def _live_filters(request: Request, museum: str) -> FiltersResponse:
    """The filter vocabulary of a live source, which is a much smaller question.

    No index, so no facet layer, no dependent counts and no exclusion: what comes back is
    one closed list with a total beside each entry, asked of the museum once per process.
    A source that cannot answer at all yields an empty vocabulary and the panel says the
    filters are unavailable rather than showing an empty box.
    """
    source = request.app.state.live_sources.get(museum)
    if source is None:  # pragma: no cover — the route's Literal bounds this
        raise HTTPException(status_code=404, detail="unknown_museum")
    try:
        options = await source.artwork_types()
    except SourceError as exc:
        logger.warning("Could not read %s filters: %s", museum, exc)
        options = []
    return FiltersResponse(
        museum=museum,
        artwork_types=[
            FilterOption(value=option.value, count=option.count, label=option.label)
            for option in options
        ],
        minimum_count=0,
        maximum_options=len(options),
        indexed_total=sum(option.count for option in options),
    )


async def _facet_labels(index: ArtworkIndexRepository) -> dict[str, str]:
    """The English label for every facet, derived from the raw values behind it.

    `artwork_facets` stores keys and nothing else, deliberately — a label repeated on every
    one of 131,000 rows is a column that can go stale. But a key cannot be turned back into
    a label: `style.chimu` was `chimú` and `style.pre-columbian` was `Pre-Columbian`, and
    neither accent nor internal capital survives a slug.

    So the labels come from the raw vocabularies, which the index already groups and counts
    for us. Three cheap queries against indexed columns, and the answer is exact rather
    than reconstructed.
    """
    labels: dict[str, str] = {}
    raw: dict[FacetGroup, dict[str, int]] = {
        "type": await index.artwork_type_counts(),
        "style": await index.term_counts("style"),
        "subject": await index.term_counts("subject"),
    }
    for group, counts in raw.items():
        for value in counts:
            if (facet := facet_for(group, value)) is not None:
                # First writer wins, and the raw values arrive most-populous-first, so a
                # merged facet is labelled after its commonest spelling when it has no
                # written label of its own.
                labels.setdefault(facet.key, facet.label_en)
    return labels


def _valid_facets(values: list[str] | None) -> list[str]:
    """Keep only what looks like a facet key, and deduplicate. For **exclusion**.

    Not a check that the facet exists: the vocabulary can change under a saved preference,
    and an unknown key should simply match nothing rather than 400. This only keeps a
    query string from putting arbitrary text into the `NOT IN` list.

    Dropping a malformed value is safe here and only here. An exclusion that is dropped
    shows the user *more* than they asked to see, which is a widening they can see and
    correct; the same treatment of an inclusion is `_included_facets` below, and it is not.
    """
    if not values:
        return []
    seen = []
    for value in values:
        group, _, rest = value.partition(".")
        if group in FACET_GROUPS and rest and value not in seen and len(value) <= 100:
            seen.append(value)
    return seen[:MAX_EXCLUSIONS]


def _included_facets(values: list[str] | None) -> list[str]:
    """The same, for **inclusion**, and deliberately more permissive.

    A value that is not a facet key is kept rather than dropped, because dropping it would
    turn "show me sculptures" into "show me anything" the moment the vocabulary moved
    under a saved preference — a filter silently ceasing to filter, which is the one
    failure the whole Explore path is written to avoid. Kept, it matches no row in
    `artwork_facets`, the selection comes back empty, and the display says so.

    Length and count are still bounded: that is what keeps a query string out of a
    thousand-placeholder `IN (...)`.
    """
    if not values:
        return []
    seen: list[str] = []
    for value in values:
        if value and len(value) <= 100 and value not in seen:
            seen.append(value)
    return seen[:MAX_INCLUSIONS]


def _options(
    unconstrained: dict[str, int],
    constrained: dict[str, int],
    labels: dict[str, str],
    limit: int | None = None,
) -> list[FilterOption]:
    """Counts to offerable options.

    Offered by the unconstrained count, ordered by it, and numbered by the constrained one
    — which is zero for anything the current selection rules out, and is therefore absent
    from `constrained` entirely. `label_for` is the last resort, for a facet whose raw
    values have gone from the index since it was tagged.
    """
    options = [
        FilterOption(
            value=value,
            count=constrained.get(value, 0),
            label=labels.get(value) or label_for(value),
        )
        for value, count in unconstrained.items()
        if count >= MIN_FILTER_COUNT
    ]
    return options[:limit] if limit is not None else options


@router.get("/preferences", response_model=PreferencesResponse)
async def read_preferences(
    preferences: PreferencesDep, settings: SettingsDep
) -> PreferencesResponse:
    """Whatever has been saved, with the defaults filling the gaps."""
    stored_interval = await preferences.get(INTERVAL_KEY)
    fields: dict[str, object] = {}
    if stored_interval is not None and stored_interval.isdigit():
        fields["interval_seconds"] = int(stored_interval)
    else:
        fields["interval_seconds"] = settings.default_interval_seconds
    if (stored_mode := await preferences.get(MODE_KEY)) is not None:
        fields["mode"] = stored_mode
    # Comma-separated since M13, the same encoding `exclude` has always used, and for the
    # same reason: a facet key is `[a-z0-9.-]` by construction and can never contain a
    # comma. A value written by an older version holds one key and decodes to a one-item
    # list, so nobody's saved filter is lost.
    for key, name, clean in (
        (ARTWORK_TYPE_KEY, "artwork_type", _included_facets),
        (STYLE_KEY, "style", _included_facets),
        (SUBJECT_KEY, "subject", _included_facets),
        (EXCLUDE_KEY, "exclude", _valid_facets),
    ):
        stored = await preferences.get(key) or ""
        fields[name] = clean([part for part in stored.split(EXCLUDE_SEPARATOR) if part])
    if (stored_museum := await preferences.get(MUSEUM_KEY)) is not None:
        fields["museum"] = stored_museum
    # Nothing saved yet means the deployment's own default, not the schema's — this is
    # what makes DEFAULT_LANGUAGE in .env do anything.
    fields["language"] = await preferences.get(LANGUAGE_KEY) or settings.default_language
    # The table stores strings. Anything that is not the stored true is false, so a value
    # written by an older version cannot switch ambient mode on by accident.
    fields["ambient"] = await preferences.get(AMBIENT_KEY) == "1"
    # Absent for everyone who installed before this existed, which reads as false — the
    # right answer: they have not said no to ambient mode, so fullscreen may say yes.
    fields["ambient_by_hand"] = await preferences.get(AMBIENT_BY_HAND_KEY) == "1"

    try:
        return PreferencesResponse(**fields)
    except ValidationError:
        # A value we no longer support — an interval removed from the menu, say. The
        # default is a better answer than a 500 on every page load.
        logger.warning("Discarding unusable stored preferences %r", fields)
        # The configured language survives the reset: it is validated at startup, so it
        # cannot be the unusable value, and falling back to English would be a second
        # surprise on top of the first.
        return PreferencesResponse(
            language=settings.default_language,
            interval_seconds=settings.default_interval_seconds,
        )


@router.put("/preferences", response_model=PreferencesResponse)
async def write_preferences(
    body: PreferencesResponse, preferences: PreferencesDep
) -> PreferencesResponse:
    """Persist the user's settings. Pydantic rejects an interval off the menu."""
    await preferences.set(INTERVAL_KEY, str(body.interval_seconds))
    await preferences.set(MODE_KEY, body.mode)
    for key, values, clean in (
        (ARTWORK_TYPE_KEY, body.artwork_type, _included_facets),
        (STYLE_KEY, body.style, _included_facets),
        (SUBJECT_KEY, body.subject, _included_facets),
        (EXCLUDE_KEY, body.exclude, _valid_facets),
    ):
        await preferences.set(key, EXCLUDE_SEPARATOR.join(clean(values)))
    await preferences.set(MUSEUM_KEY, body.museum)
    await preferences.set(LANGUAGE_KEY, body.language)
    await preferences.set(AMBIENT_KEY, "1" if body.ambient else "0")
    await preferences.set(AMBIENT_BY_HAND_KEY, "1" if body.ambient_by_hand else "0")
    return body


@router.get("/interpretation/{artwork_id}", response_model=InterpretationResponse)
async def read_interpretation(
    artwork_id: Annotated[int, Path(gt=0)],
    interpretation: InterpretationDep,
    language: Annotated[Literal["en", "pl"], Query()] = "en",
) -> InterpretationResponse:
    """Interpret one artwork, on demand.

    Generated only when someone asks — never on rotation. `docs/ai-system.md` puts an
    order of magnitude of cost on that one decision, because most artworks are shown and
    never asked about.

    Every failure here is quiet by design: the display keeps the museum's own facts and
    shows a note. None of these are dialogs.
    """
    if not interpretation.enabled:
        # Not an error. The app is complete with no AI configured, and the frontend uses
        # /health to avoid asking in the first place.
        raise HTTPException(status_code=503, detail="ai_disabled")

    try:
        result = await interpretation.interpret(artwork_id, language)
    except ArtworkNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artwork_unknown") from exc
    except BudgetExhaustedError as exc:
        # Not a failure. We are choosing not to spend more today, and the display says
        # something different about that than about a provider being down.
        logger.info("Interpretation refused: %s", exc)
        raise HTTPException(status_code=503, detail="ai_budget_exhausted") from exc
    except CircuitOpenError as exc:
        # Already logged when it opened. Repeating it on every refusal would bury the
        # transition that actually matters.
        logger.debug("Interpretation refused: %s", exc)
        raise HTTPException(status_code=503, detail="ai_unavailable") from exc
    except AiError as exc:
        logger.warning("Interpretation failed for artwork %s: %s", artwork_id, exc)
        raise HTTPException(status_code=503, detail="ai_unavailable") from exc

    return InterpretationResponse(
        artwork_id=artwork_id,
        language=result.language,
        provider=interpretation.provider_name or "",
        model=interpretation.model or "",
        visual_description=result.visual_description,
        interpretation=result.interpretation,
        themes=result.themes,
        look_closer=result.look_closer,
    )


@router.get("/access-description/{artwork_id}", response_model=VisualDescriptionResponse)
async def read_visual_description(
    artwork_id: Annotated[int, Path(gt=0)],
    interpretation: InterpretationDep,
    language: Annotated[Literal["en", "pl"], Query()] = "en",
) -> VisualDescriptionResponse:
    """Describe one artwork for somebody who cannot see it.

    On demand, cached, and off the same budget and breaker as the interpretation — see the
    service. A second request for the same artwork is a cache hit and costs nothing, which
    is what lets the display offer "read it again" without asking anyone's permission.

    The failures are more numerous than the interpretation's because there are two extra
    ways to be unable to answer, and both are ordinary rather than faults: the provider may
    not do this at all, and the artwork may have nothing visual in its metadata to build a
    description from. Neither is a provider being down, and the display says something
    different about each.
    """
    if not interpretation.enabled:
        raise HTTPException(status_code=503, detail="ai_disabled")

    try:
        result = await interpretation.describe(artwork_id, language)
    except DescriptionUnsupportedError as exc:
        # A capability the configured provider does not have. /api/health says so too, so
        # the display should not have asked — but a key can change while a page is open.
        logger.info("Description refused: %s", exc)
        raise HTTPException(status_code=503, detail="access_unsupported") from exc
    except NotDescribableError as exc:
        # 422 rather than 404: the artwork exists and is on screen. What is missing is the
        # museum's own visual description of it, and inventing one is the failure this
        # whole feature is written against.
        logger.info("Description refused: %s", exc)
        raise HTTPException(status_code=422, detail="access_not_describable") from exc
    except ArtworkNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artwork_unknown") from exc
    except BudgetExhaustedError as exc:
        logger.info("Description refused: %s", exc)
        raise HTTPException(status_code=503, detail="ai_budget_exhausted") from exc
    except CircuitOpenError as exc:
        logger.debug("Description refused: %s", exc)
        raise HTTPException(status_code=503, detail="ai_unavailable") from exc
    except AiError as exc:
        logger.warning("Description failed for artwork %s: %s", artwork_id, exc)
        raise HTTPException(status_code=503, detail="ai_unavailable") from exc

    artwork = await interpretation.find_artwork(artwork_id)
    alt = artwork.thumbnail.alt_text if artwork.thumbnail else None
    return VisualDescriptionResponse(
        artwork_id=artwork_id,
        language=result.language,
        provider=interpretation.provider_name or "",
        model=interpretation.model or "",
        summary=result.summary,
        description=result.description,
        # Which museum field carried the visual content. `find_artwork` is a cache hit or
        # an indexed read here — the description above already went through it — so this
        # costs a lookup rather than a request.
        grounded_in="alt_text" if (alt or "").strip() else "description",
    )


@router.get("/ai/key", response_model=AiKeyResponse)
async def read_ai_key(credentials: AiCredentialsDep) -> AiKeyResponse:
    """Whether a key is set, where it lives, and its last four characters.

    Never the key. The panel needs enough to tell the user which key is in use and to warn
    them when it is sitting unencrypted in the database, and that is exactly this much.
    """
    return _key_response(credentials.status())


@router.put("/ai/key", response_model=AiKeyResponse)
async def write_ai_key(body: AiKeyRequest, credentials: AiCredentialsDep) -> AiKeyResponse:
    """Save a bring-your-own key and start using it, without a restart.

    The key is not validated against the vendor here. That would cost a real call, and a
    wrong key announces itself clearly enough at the first interpretation.
    """
    try:
        status = await credentials.save(body.provider, body.api_key.get_secret_value())
    except CredentialStoreError as exc:
        # The keyring refused. Nothing is stored and nothing changed, which is worth
        # saying differently from "the key is wrong".
        logger.warning("Could not store the %s key: %s", body.provider, exc)
        raise HTTPException(status_code=503, detail="key_store_unavailable") from exc
    return _key_response(status)


@router.delete("/ai/key", response_model=AiKeyResponse)
async def delete_ai_key(credentials: AiCredentialsDep) -> AiKeyResponse:
    """Forget the stored key. Falls back to whatever `.env` configures, or to no AI."""
    try:
        status = await credentials.clear()
    except CredentialStoreError as exc:
        logger.warning("Could not remove the stored key: %s", exc)
        raise HTTPException(status_code=503, detail="key_store_unavailable") from exc
    return _key_response(status)


def _key_response(status: AiKeyStatus) -> AiKeyResponse:
    """One place where the service's answer becomes an HTTP body, so there is one place
    to check that a key cannot leak through it."""
    return AiKeyResponse(
        enabled=status.enabled,
        provider=status.provider,
        model=status.model,
        source=status.source,
        key_hint=status.key_hint,
        storage=status.storage,
    )


@router.get("/stats", response_model=StatsResponse)
async def stats(
    request: Request,
    interpretation: InterpretationDep,
    client: ClientDep,
    index: IndexDep,
    usage: UsageDep,
) -> StatsResponse:
    """Operational numbers, for whoever is running this on a wall somewhere.

    Deliberately separate from /api/health, which answers "can I use this?" and is read by
    the frontend at boot. Nothing here is read by the frontend at all; it exists so that
    "the interpretations feel slow" or "the pictures keep skipping" can be checked rather
    than guessed at.
    """
    return StatsResponse(
        uptime_seconds=monotonic() - request.app.state.started_at,
        indexed_artworks=await index.count(),
        interpretation_cache=CacheStats(
            hits=interpretation.cache.hits,
            misses=interpretation.cache.misses,
            hit_ratio=round(interpretation.cache.hit_ratio, 4),
        ),
        provider=ProviderStats(
            name=interpretation.provider_name,
            model=interpretation.model,
            calls=interpretation.calls.total,
            errors=interpretation.calls.errors,
            error_rate=round(interpretation.calls.error_rate, 4),
            average_ms=round(interpretation.latency.average_ms, 1),
            max_ms=round(interpretation.latency.max_ms, 1),
            circuit_open=interpretation.circuit_open,
        ),
        aic=AicStats(
            requests=client.requests.total,
            errors=client.requests.errors,
            error_rate=round(client.requests.error_rate, 4),
        ),
        usage=UsageStats(day=today(), providers=await usage.totals()),
    )


@router.get("/scoring", response_model=ScoringResponse)
async def read_scoring() -> ScoringResponse:
    """What curated mode weighs, taken from the code.

    The panel explains the scoring in a paragraph and a list, and the numbers in that list
    come from here rather than from prose somebody would have to remember to update. A
    retuned weight changes what the UI says, in the same commit, without anyone noticing
    it needed to. ADR-0006's transparency claim is only true if this cannot drift.
    """
    total = sum(WEIGHTS.values()) or 1.0
    return ScoringResponse(
        weights=[
            ScoringWeight(name=name, weight=weight, share=round(weight / total, 4))
            for name, weight in sorted(WEIGHTS.items(), key=lambda pair: -pair[1])
        ]
    )


@router.get("/favorites", response_model=list[FeedbackItem])
async def read_favorites(
    feedback: FeedbackDep,
    kind: Annotated[Literal["like", "dislike", "hide"], Query()] = "like",
) -> list[FeedbackItem]:
    """Everything with one verdict, across every museum. Most recent first."""
    return [FeedbackItem(**vars(item)) for item in await feedback.all(kind)]


@router.get("/favorites/summary", response_model=FeedbackSummary)
async def read_favorites_summary(feedback: FeedbackDep) -> FeedbackSummary:
    """How much the personal mode has to work with.

    Read by the panel so it can say "showing curated picks until you have liked a few
    more" rather than offering a mode that silently is not one yet.
    """
    counts = await feedback.counts()
    return FeedbackSummary(
        likes=counts["like"],
        dislikes=counts["dislike"],
        hides=counts["hide"],
        personalising=counts["like"] >= MIN_LIKES_FOR_PROFILE,
        minimum_likes=MIN_LIKES_FOR_PROFILE,
    )


@router.put("/favorites/{artwork_id}", response_model=FeedbackItem)
async def write_favorite(
    artwork_id: Annotated[int, Path(gt=0)],
    body: FeedbackRequest,
    feedback: FeedbackDep,
) -> FeedbackItem:
    """Like, dislike or hide one artwork, replacing whatever it was before.

    The snapshot in the body is stored as sent: the server may never have seen this
    artwork, because the display's second and third tiers serve straight from AIC and from
    the bundled set, and Cleveland is never indexed at all. See migration 009 for why there
    is no foreign key here, and migration 010 for why the museum is part of the key.
    """
    stored = await feedback.set(
        artwork_id,
        body.kind,
        museum=body.museum,
        title=body.title,
        artist=body.artist,
        image_id=body.image_id,
    )
    return FeedbackItem(**vars(stored))


@router.delete("/favorites/{artwork_id}", status_code=204)
async def delete_favorite(
    artwork_id: Annotated[int, Path(gt=0)],
    feedback: FeedbackDep,
    museum: Annotated[Literal["aic", "cma"], Query()] = "aic",
) -> Response:
    """Forget a verdict. Idempotent: forgetting nothing is not an error."""
    await feedback.clear(artwork_id, museum)
    return Response(status_code=204)


@router.get("/health", response_model=HealthResponse)
async def health(interpretation: InterpretationDep) -> HealthResponse:
    """Liveness, and whether AI is available. Deliberately does not call AIC.

    The AI block is here so the frontend can decide whether to offer the feature without
    asking for an interpretation and being told no. `docs/ai-system.md` also wants the
    circuit breaker's state surfaced here once it exists.
    """
    return HealthResponse(
        ai=AiStatus(
            enabled=interpretation.enabled,
            describes=interpretation.describes,
            provider=interpretation.provider_name,
            model=interpretation.model,
            circuit_open=interpretation.circuit_open,
        )
    )
