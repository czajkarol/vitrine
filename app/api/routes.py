"""HTTP routes. Shapes in, shapes out — orchestration belongs below this layer."""

import logging
import re
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from app.api.schemas import ArtworkResponse
from app.domain.artwork import CACHED_IIIF_WIDTHS, PREFERRED_IIIF_WIDTH
from app.providers.aic.client import AicClient, AicError, AicUnavailableError

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


ClientDep = Annotated[AicClient, Depends(get_client)]


@router.get("/artwork/random", response_model=ArtworkResponse)
async def random_artwork(request: Request, client: ClientDep) -> ArtworkResponse:
    """One random public-domain artwork with a usable image."""
    try:
        result = await client.random_displayable()
    except AicUnavailableError as exc:
        logger.warning("AIC unavailable serving /artwork/random: %s", exc)
        raise HTTPException(status_code=503, detail="aic_unavailable") from exc
    except AicError as exc:
        logger.error("AIC error serving /artwork/random: %s", exc)
        raise HTTPException(status_code=502, detail="aic_error") from exc

    if result is None:
        raise HTTPException(status_code=404, detail="no_displayable_artwork")

    artwork, iiif_base = result
    # Remembered so the image proxy never has to guess a IIIF base or hardcode one.
    request.app.state.iiif_base = iiif_base
    return ArtworkResponse.from_domain(artwork, iiif_base)


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


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness only. Deliberately does not call AIC."""
    return {"status": "ok"}
