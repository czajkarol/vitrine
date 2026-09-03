"""HTTP routes. Shapes in, shapes out — orchestration belongs below this layer."""

import logging
import re
from time import monotonic
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError

from app.api.schemas import (
    AicStats,
    AiKeyRequest,
    AiKeyResponse,
    AiStatus,
    ArtworkResponse,
    CacheStats,
    FilterOption,
    FiltersResponse,
    HealthResponse,
    InterpretationResponse,
    PreferencesResponse,
    ProviderStats,
    StatsResponse,
    UsageStats,
)
from app.core.config import Settings
from app.domain.artwork import CACHED_IIIF_WIDTHS, PREFERRED_IIIF_WIDTH
from app.domain.rate_limit import RateLimiter
from app.providers.ai.base import AiError
from app.providers.aic.client import AicClient, AicError, AicUnavailableError
from app.repositories.ai_usage import AiUsageRepository, today
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.credentials import CredentialStoreError
from app.repositories.preferences import PreferencesRepository
from app.services.ai_credentials import AiCredentialService, AiKeyStatus
from app.services.interpretation import (
    ArtworkNotFoundError,
    BudgetExhaustedError,
    CircuitOpenError,
    InterpretationService,
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

# Below this, a filter cannot sustain a rotation and is not offered at all.
MIN_FILTER_COUNT: Final[int] = 40

# And above this many options, a list stops being a menu. Applies to style and subject,
# whose vocabularies run to thousands of values; the 45 artwork types are all offered.
MAX_FILTER_OPTIONS: Final[int] = 30

INTERVAL_KEY: Final[str] = "interval_seconds"
MODE_KEY: Final[str] = "mode"
ARTWORK_TYPE_KEY: Final[str] = "artwork_type"
STYLE_KEY: Final[str] = "style"
SUBJECT_KEY: Final[str] = "subject"
LANGUAGE_KEY: Final[str] = "language"
AMBIENT_KEY: Final[str] = "ambient"


@router.get("/artwork/random", response_model=ArtworkResponse, dependencies=[RateLimited])
async def random_artwork(
    request: Request,
    selection: SelectionDep,
    mode: Annotated[Literal["random", "curated"], Query()] = "random",
    artwork_type: Annotated[str | None, Query(max_length=100)] = None,
    style: Annotated[str | None, Query(max_length=100)] = None,
    subject: Annotated[str | None, Query(max_length=100)] = None,
) -> ArtworkResponse:
    """One random public-domain artwork with a usable image.

    The service decides where it comes from — local index first, then AIC, then the
    bundled set (ADR-0003). This route only shapes the answer.
    """
    query = SelectionQuery(
        curated=mode == "curated", artwork_type=artwork_type, style=style, subject=subject
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

    # Remembered so the image proxy never has to guess a IIIF base or hardcode one.
    request.app.state.iiif_base = result.iiif_base
    return ArtworkResponse.from_domain(result.artwork, result.iiif_base, source=result.source)


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
async def read_filters(index: IndexDep) -> FiltersResponse:
    """The Explore vocabulary, built from the index rather than a hardcoded list.

    Three vocabularies now. Artwork type is closed and small, so all of it is offered;
    style and subject are open and large, so they are cut to the most populous
    `MAX_FILTER_OPTIONS` as well as to what clears `MIN_FILTER_COUNT`.
    """
    return FiltersResponse(
        artwork_types=_options(await index.artwork_type_counts()),
        styles=_options(await index.term_counts("style"), limit=MAX_FILTER_OPTIONS),
        subjects=_options(await index.term_counts("subject"), limit=MAX_FILTER_OPTIONS),
        minimum_count=MIN_FILTER_COUNT,
        maximum_options=MAX_FILTER_OPTIONS,
        indexed_total=await index.count(),
    )


def _options(counts: dict[str, int], limit: int | None = None) -> list[FilterOption]:
    """Counts to offerable options: drop the thin ones, keep the order, cap the length."""
    options = [
        FilterOption(value=value, count=count)
        for value, count in counts.items()
        if count >= MIN_FILTER_COUNT
    ]
    return options[:limit] if limit is not None else options


@router.get("/preferences", response_model=PreferencesResponse)
async def read_preferences(
    preferences: PreferencesDep, settings: SettingsDep
) -> PreferencesResponse:
    """Whatever has been saved, with the defaults filling the gaps."""
    stored_interval = await preferences.get(INTERVAL_KEY)
    stored_type = await preferences.get(ARTWORK_TYPE_KEY)
    fields: dict[str, object] = {}
    if stored_interval is not None and stored_interval.isdigit():
        fields["interval_seconds"] = int(stored_interval)
    else:
        fields["interval_seconds"] = settings.default_interval_seconds
    if (stored_mode := await preferences.get(MODE_KEY)) is not None:
        fields["mode"] = stored_mode
    # An empty string means "no filter"; storing None is not possible in this table.
    fields["artwork_type"] = stored_type or None
    fields["style"] = await preferences.get(STYLE_KEY) or None
    fields["subject"] = await preferences.get(SUBJECT_KEY) or None
    # Nothing saved yet means the deployment's own default, not the schema's — this is
    # what makes DEFAULT_LANGUAGE in .env do anything.
    fields["language"] = await preferences.get(LANGUAGE_KEY) or settings.default_language
    # The table stores strings. Anything that is not the stored true is false, so a value
    # written by an older version cannot switch ambient mode on by accident.
    fields["ambient"] = await preferences.get(AMBIENT_KEY) == "1"

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
    await preferences.set(ARTWORK_TYPE_KEY, body.artwork_type or "")
    await preferences.set(STYLE_KEY, body.style or "")
    await preferences.set(SUBJECT_KEY, body.subject or "")
    await preferences.set(LANGUAGE_KEY, body.language)
    await preferences.set(AMBIENT_KEY, "1" if body.ambient else "0")
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
            provider=interpretation.provider_name,
            model=interpretation.model,
            circuit_open=interpretation.circuit_open,
        )
    )
