"""The Art Institute of Chicago API client.

The only module that knows AIC's JSON shape. It returns domain models; nothing downstream
sees a raw response dict. When AIC renames a field, this file changes and nothing else.
"""

import asyncio
import logging
import random
from collections.abc import Iterator
from types import TracebackType
from typing import Any, Final

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.artwork import (
    CACHED_IIIF_WIDTHS,
    PREFERRED_IIIF_WIDTH,
    Artwork,
    ArtworkPage,
    iiif_url,
)
from app.domain.metrics import Tally

logger = logging.getLogger(__name__)

# Explicit field list. A default search response carries only seven fields and includes
# neither image_id nor is_public_domain, which makes the public-domain filter impossible
# to apply — so this is required, not an optimisation. See docs/aic-api.md.
ARTWORK_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "title",
    "artist_title",
    "artist_display",
    "date_display",
    "medium_display",
    "image_id",
    "is_public_domain",
    "is_boosted",
    "thumbnail",
    "color",
    "description",
    "credit_line",
    "department_title",
    "place_of_origin",
    "artwork_type_title",
    "main_reference_number",
    # M3.5. Multi-valued and often empty; AIC returns [] rather than null for both.
    "style_titles",
    "subject_titles",
)

# /artworks/search refuses anything past page * limit == 1000.
SEARCH_RECORD_CAP: Final[int] = 1000
MAX_LIMIT: Final[int] = 100

RETRY_STATUS: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS: Final[int] = 3


class AicError(RuntimeError):
    """Any failure talking to AIC."""


class AicUnavailableError(AicError):
    """AIC could not be reached, or kept failing. Callers should degrade, not crash."""


class AicClient:
    """Async client for the AIC public API.

    Construct one per application and reuse it; it owns a connection pool and the shared
    rate limiter, both of which are pointless if recreated per request.
    """

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        rng: random.Random | None = None,
    ) -> None:
        from app.providers.aic.throttle import RateLimiter

        self._settings = settings
        self._rng = rng or random.Random()
        # One request in, one outcome counted, whatever the retries did on the way. What
        # /api/stats reports is how often a caller asked AIC for something and did not
        # get it — retries are this client's business, not the display's.
        self.requests = Tally()
        self._limiter = RateLimiter(settings.aic_max_requests_per_minute)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.aic_base_url,
            timeout=settings.aic_timeout_seconds,
            headers={"AIC-User-Agent": settings.aic_user_agent},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "AicClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --- requests -----------------------------------------------------------------

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with the throttle applied and retries on transient failures only."""
        try:
            payload = await self._get_uncounted(path, params)
        except AicError:
            self.requests.record(error=True)
            raise
        self.requests.record()
        return payload

    async def _get_uncounted(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._limiter.acquire()
            try:
                response = await self._client.get(path, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                logger.warning("AIC %s attempt %d/%d: %s", path, attempt, MAX_ATTEMPTS, exc)
            else:
                if response.status_code in RETRY_STATUS:
                    last = AicUnavailableError(f"AIC returned {response.status_code} for {path}")
                    logger.warning(
                        "AIC %s attempt %d/%d: HTTP %d",
                        path,
                        attempt,
                        MAX_ATTEMPTS,
                        response.status_code,
                    )
                elif response.is_error:
                    # 400/403/404 are our bug or a genuine absence. Retrying repeats it.
                    raise AicError(f"AIC returned {response.status_code} for {path}")
                else:
                    parsed: dict[str, Any] = response.json()
                    return parsed

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))

        raise AicUnavailableError(
            f"AIC unreachable after {MAX_ATTEMPTS} attempts: {last}"
        ) from last

    # --- reads --------------------------------------------------------------------

    async def search_public_domain(self, limit: int = 100, page: int = 1) -> ArtworkPage:
        """Search public-domain works.

        Bounded by AIC's 1,000-record search cap, which this refuses to exceed rather than
        letting the API return a 403.
        """
        limit = min(limit, MAX_LIMIT)
        if page * limit > SEARCH_RECORD_CAP:
            raise ValueError(
                f"page {page} at limit {limit} exceeds AIC's {SEARCH_RECORD_CAP}-record "
                "search cap; use the listing endpoint for bulk access"
            )
        payload = await self._get(
            "/artworks/search",
            {
                "limit": limit,
                "page": page,
                "fields": ",".join(ARTWORK_FIELDS),
                "query[term][is_public_domain]": "true",
            },
        )
        return self._parse_page(payload)

    async def list_artworks(self, page: int = 1, limit: int = MAX_LIMIT) -> ArtworkPage:
        """Walk the collection through the plain listing endpoint.

        Unlike `/artworks/search` this is not capped, so it is the only way to enumerate
        all 132,740 records — which is what `scripts/build_index.py` needs and what
        ADR-0003 depends on. It does not accept a public-domain filter, so eligibility is
        decided locally from the fields that come back.
        """
        payload = await self._get(
            "/artworks",
            {"limit": min(limit, MAX_LIMIT), "page": page, "fields": ",".join(ARTWORK_FIELDS)},
        )
        return self._parse_page(payload)

    async def get(self, artwork_id: int) -> Artwork | None:
        """Fetch one artwork. Returns None when AIC does not have it."""
        try:
            payload = await self._get(
                f"/artworks/{artwork_id}", {"fields": ",".join(ARTWORK_FIELDS)}
            )
        except AicUnavailableError:
            raise
        except AicError as exc:
            if "404" in str(exc):
                return None
            raise
        record = payload.get("data")
        if not isinstance(record, dict):
            return None
        return self._parse_artwork(record)

    async def random_displayable(self) -> tuple[Artwork, str] | None:
        """One random public-domain artwork that has an image, with the IIIF base.

        M0 selection: a random page inside the search cap, then a random eligible record
        from it. This reaches only the top 1,000 relevance-ranked public-domain works,
        which is precisely the limitation the local index exists to remove (ADR-0003).
        It is the thin vertical slice, and M2 replaces it.
        """
        limit = MAX_LIMIT
        max_page = SEARCH_RECORD_CAP // limit
        for page in self._rng.sample(range(1, max_page + 1), k=max_page):
            page_result = await self.search_public_domain(limit=limit, page=page)
            candidates = page_result.displayable()
            if candidates:
                return self._rng.choice(candidates), page_result.iiif_base
            logger.warning("AIC search page %d held no displayable artwork", page)
        return None

    async def fetch_image(self, iiif_base: str, image_id: str, width: int) -> httpx.Response:
        """Fetch IIIF image bytes server-side, for the ADR-0008 proxy fallback.

        Sends a browser User-Agent alongside AIC-User-Agent because the IIIF service is
        behind Cloudflare and challenges anything else. Deliberately not throttled by the
        API limiter: this is a different host and a different budget.
        """
        if width not in CACHED_IIIF_WIDTHS:
            raise ValueError(f"width {width} is not a cached IIIF width")
        url = iiif_url(iiif_base, image_id, width)
        try:
            return await self._client.get(
                url,
                headers={
                    "User-Agent": self._settings.image_fetch_user_agent,
                    "AIC-User-Agent": self._settings.aic_user_agent,
                },
                timeout=self._settings.aic_timeout_seconds * 3,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Contained here so httpx exceptions never surface above providers/.
            raise AicUnavailableError(f"IIIF fetch failed for {image_id}: {exc}") from exc

    # --- parsing ------------------------------------------------------------------

    @staticmethod
    def _parse_artwork(record: dict[str, Any]) -> Artwork:
        return Artwork.model_validate(record)

    @staticmethod
    def _parse_records(records: list[Any]) -> Iterator[Artwork]:
        """Parse what we can and skip what we cannot, loudly.

        A single unparseable record used to abort the whole crawl — one artwork with a
        null title killed a 1,328-page walk at page 1,121. Over a collection this size
        some rows will always be odd, and losing one is much cheaper than losing the run.
        The warning is what keeps this from hiding a real API change: a handful of these
        is data, a page of them is a contract break.
        """
        for record in records:
            if not isinstance(record, dict) or "id" not in record:
                continue
            try:
                yield Artwork.model_validate(record)
            except ValidationError as exc:
                logger.warning("Skipping unparseable artwork %s: %s", record.get("id"), exc)

    def _parse_page(self, payload: dict[str, Any]) -> ArtworkPage:
        config = payload.get("config") or {}
        iiif_base = config.get("iiif_url")
        if not iiif_base:
            # Never hardcode a fallback here. Without it we cannot build an image URL,
            # and guessing would paper over an AIC change we want to hear about.
            raise AicError("AIC response carried no config.iiif_url")
        records = payload.get("data") or []
        artworks = tuple(self._parse_records(records))
        pagination = payload.get("pagination") or {}
        return ArtworkPage(
            artworks=artworks,
            iiif_base=iiif_base,
            total=pagination.get("total"),
            total_pages=pagination.get("total_pages"),
            current_page=pagination.get("current_page"),
        )


__all__ = [
    "ARTWORK_FIELDS",
    "PREFERRED_IIIF_WIDTH",
    "AicClient",
    "AicError",
    "AicUnavailableError",
]
