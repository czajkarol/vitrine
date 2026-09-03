"""HTTP routes. Shapes in, shapes out — orchestration belongs below this layer."""

import logging
import re
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import ValidationError

from app.api.schemas import (
    ArtworkResponse,
    FilterOption,
    FiltersResponse,
    PreferencesResponse,
)
from app.domain.artwork import CACHED_IIIF_WIDTHS, PREFERRED_IIIF_WIDTH
from app.providers.aic.client import AicClient, AicError, AicUnavailableError
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.preferences import PreferencesRepository
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


def get_index(request: Request) -> ArtworkIndexRepository:
    return ArtworkIndexRepository(request.app.state.database)


ClientDep = Annotated[AicClient, Depends(get_client)]
SelectionDep = Annotated[SelectionService, Depends(get_selection)]
PreferencesDep = Annotated[PreferencesRepository, Depends(get_preferences)]
IndexDep = Annotated[ArtworkIndexRepository, Depends(get_index)]

# Below this, a filter cannot sustain a rotation and is not offered at all.
MIN_FILTER_COUNT: Final[int] = 40

INTERVAL_KEY: Final[str] = "interval_minutes"
MODE_KEY: Final[str] = "mode"
ARTWORK_TYPE_KEY: Final[str] = "artwork_type"


@router.get("/artwork/random", response_model=ArtworkResponse)
async def random_artwork(
    request: Request,
    selection: SelectionDep,
    mode: Annotated[Literal["random", "curated"], Query()] = "random",
    artwork_type: Annotated[str | None, Query(max_length=100)] = None,
) -> ArtworkResponse:
    """One random public-domain artwork with a usable image.

    The service decides where it comes from — local index first, then AIC, then the
    bundled set (ADR-0003). This route only shapes the answer.
    """
    query = SelectionQuery(curated=mode == "curated", artwork_type=artwork_type)
    try:
        result = await selection.next_artwork(query)
    except AicUnavailableError as exc:  # pragma: no cover — the service absorbs these
        logger.warning("AIC unavailable serving /artwork/random: %s", exc)
        raise HTTPException(status_code=503, detail="aic_unavailable") from exc
    except AicError as exc:  # pragma: no cover — the service absorbs these
        logger.error("AIC error serving /artwork/random: %s", exc)
        raise HTTPException(status_code=502, detail="aic_error") from exc

    if result is None:
        if query.artwork_type:
            # A filter that matches nothing is a different situation from the API being
            # down, and the display says something different about it.
            raise HTTPException(status_code=404, detail="no_matching_artwork")
        # Every tier came up empty: no index, no network, no bundled set.
        raise HTTPException(status_code=503, detail="aic_unavailable")

    # Remembered so the image proxy never has to guess a IIIF base or hardcode one.
    request.app.state.iiif_base = result.iiif_base
    return ArtworkResponse.from_domain(result.artwork, result.iiif_base, source=result.source)


@router.get("/image/{image_id}")
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
    """The Explore vocabulary, built from the index rather than a hardcoded list."""
    counts = await index.artwork_type_counts()
    options = [
        FilterOption(value=value, count=count)
        for value, count in counts.items()
        if count >= MIN_FILTER_COUNT
    ]
    return FiltersResponse(
        artwork_types=options,
        minimum_count=MIN_FILTER_COUNT,
        indexed_total=await index.count(),
    )


@router.get("/preferences", response_model=PreferencesResponse)
async def read_preferences(preferences: PreferencesDep) -> PreferencesResponse:
    """Whatever has been saved, with the defaults filling the gaps."""
    stored_interval = await preferences.get(INTERVAL_KEY)
    stored_type = await preferences.get(ARTWORK_TYPE_KEY)
    fields: dict[str, object] = {}
    if stored_interval is not None and stored_interval.isdigit():
        fields["interval_minutes"] = int(stored_interval)
    if (stored_mode := await preferences.get(MODE_KEY)) is not None:
        fields["mode"] = stored_mode
    # An empty string means "no filter"; storing None is not possible in this table.
    fields["artwork_type"] = stored_type or None

    try:
        return PreferencesResponse(**fields)
    except ValidationError:
        # A value we no longer support — an interval removed from the menu, say. The
        # default is a better answer than a 500 on every page load.
        logger.warning("Discarding unusable stored preferences %r", fields)
        return PreferencesResponse()


@router.put("/preferences", response_model=PreferencesResponse)
async def write_preferences(
    body: PreferencesResponse, preferences: PreferencesDep
) -> PreferencesResponse:
    """Persist the user's settings. Pydantic rejects an interval off the menu."""
    await preferences.set(INTERVAL_KEY, str(body.interval_minutes))
    await preferences.set(MODE_KEY, body.mode)
    await preferences.set(ARTWORK_TYPE_KEY, body.artwork_type or "")
    return body


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness only. Deliberately does not call AIC."""
    return {"status": "ok"}
