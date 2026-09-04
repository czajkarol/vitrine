"""The Cleveland Museum of Art Open Access API.

The only module that knows CMA's JSON shape. It returns domain `Artwork` models wrapped in
`SourceArtwork`; nothing downstream sees a raw response dict. Measured against the live API
on 2026-09-04 and again on the day this was written — the facts below are from responses,
not from documentation.

**What Cleveland is, in one paragraph.** No API key and no published rate limit. 41,512
records that are `share_license_status == "CC0"` *and* carry an image, which is the pair of
flags ADR-0007's hard filter maps onto. `skip` pages the whole set — there is no equivalent
of AIC's 1,000-record search cap — and `info.total` on any response is the real count for
the parameters sent, which is where the filter counts come from.

**What Cleveland is not.** There is no IIIF service: a record carries `images.web`,
`images.print` and `images.full`, three fixed URLs, and `full` is a TIFF that browsers do
not display. So there is no width ladder and no proxy fallback, and `SourceArtwork` carries
a finished URL instead of a base and an id.

Three fields vitrine leans on are simply absent, which ADR-0012 called the finding that
decides how far this goes and ADR-0013 accepts explicitly:

- no `lqip`, so the crossfade starts from nothing rather than from a blur;
- no `alt_text`, so the `alt` attribute falls back to the title and the AI features are
  not offered on a Cleveland artwork at all;
- no `color`, so the overlay uses its default scrim, which M8 already made strong enough
  to stand alone.

`description` is present and often good — better than AIC's, and on more records — so the
overlay has something to show.
"""

import asyncio
import logging
import random
import re
from types import TracebackType
from typing import Any, Final

import httpx

from app.core.config import Settings
from app.domain.artwork import Artwork, Thumbnail
from app.domain.metrics import Tally
from app.providers.source import SourceArtwork, SourceError, SourceFilter

logger = logging.getLogger(__name__)

CMA_KEY: Final[str] = "cma"

BASE_URL: Final[str] = "https://openaccess-api.clevelandart.org/api"

# Both are required on every request. `cc0` is the licence flag — a per-record fact of the
# same kind as AIC's `is_public_domain`, which is why ADR-0007's hard filter transfers
# without reinterpretation — and `has_image` is the other half of "displayable".
LICENCE_PARAMS: Final[dict[str, str]] = {"cc0": "1", "has_image": "1"}

# How many records to pull around a random offset. One request either way; taking ten and
# choosing locally costs the same call and stops a page whose only record is unusable from
# being a dead end.
SAMPLE_SIZE: Final[int] = 10

# The artwork types worth offering, in the order the panel shows them. A closed list rather
# than a vocabulary derived from the data, because Cleveland has no facet endpoint and
# deriving one would mean walking the collection — which is exactly the indexing this
# source exists not to do. Sampled across the corpus on 2026-09-04; these are the types
# with enough behind them to sustain a rotation, and the count beside each one is asked of
# the museum rather than guessed.
OFFERED_TYPES: Final[tuple[str, ...]] = (
    "Painting",
    "Print",
    "Drawing",
    "Photograph",
    "Sculpture",
    "Textile",
    "Ceramic",
    "Metalwork",
    "Jewelry",
    "Furniture and woodwork",
)

# How long a filter count is trusted. The totals move when Cleveland publishes, which is
# not often, and the alternative is ten requests every time the settings panel opens.
FILTER_CACHE_SECONDS: Final[float] = 3600.0

# `creators[].description` reads "Giovanni Battista Piranesi (Italian, 1720-1778)".
# The overlay wants the name; the dates belong to the artist, not to this artwork,
# and AIC's equivalent field carries the name alone.
_ARTIST_SUFFIX: Final[re.Pattern[str]] = re.compile(r"\s*\([^()]*\)\s*$")


class CmaClient:
    """Implements `ArtworkSource` against openaccess-api.clevelandart.org.

    Construct one per application and reuse it: it owns a connection pool and the filter
    count cache, both of which are pointless if recreated per request.
    """

    key = CMA_KEY

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._rng = rng or random.Random()
        self.requests = Tally()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=settings.aic_timeout_seconds,
            # Cleveland asks for nothing in particular, but identifying honestly is the
            # same courtesy AIC asks for by name and costs nothing to extend.
            headers={"User-Agent": settings.aic_user_agent},
            follow_redirects=True,
        )
        # Populated on first use and shared by every later panel open. `None` means "not
        # asked yet", which is distinct from "asked and the museum had nothing".
        self._filters: list[SourceFilter] | None = None
        self._filters_at: float = 0.0
        # One in-flight fetch at a time. Ten requests are cheap once and silly ten times
        # over, and the settings panel is perfectly capable of being opened twice quickly.
        self._filters_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "CmaClient":
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
        """GET and parse, converting every transport failure into a `SourceError`.

        No retries. A live source is one tier of a display that already retries on its own
        clock, and a second layer of them would only make a slow museum look like a hung
        one.
        """
        try:
            response = await self._client.get(path, params={**LICENCE_PARAMS, **params})
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.requests.record(error=True)
            # Contained here so no httpx exception type surfaces above `providers/`.
            raise SourceError(f"Cleveland unreachable: {exc}") from exc
        if response.is_error:
            self.requests.record(error=True)
            raise SourceError(f"Cleveland returned {response.status_code} for {path}")
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            self.requests.record(error=True)
            raise SourceError(f"Cleveland returned unparseable JSON for {path}") from exc
        self.requests.record()
        return payload

    # --- reads --------------------------------------------------------------------

    async def random(self, artwork_type: str | None = None) -> SourceArtwork | None:
        """One CC0 artwork with an image, optionally of one type.

        Two requests: one to learn how many records match, one to take a sample from a
        random offset inside them. The count is not cached with the filter counts because
        it is asked for one selection rather than for the menu, and because a stale total
        here is a `skip` past the end of the result set.
        """
        params: dict[str, Any] = {"limit": 1, "skip": 0}
        if artwork_type:
            params["type"] = artwork_type
        head = await self._get("/artworks/", params)
        total = int((head.get("info") or {}).get("total") or 0)
        if total <= 0:
            return None

        skip = self._rng.randrange(max(total - SAMPLE_SIZE, 0) + 1)
        page = await self._get("/artworks/", {**params, "limit": SAMPLE_SIZE, "skip": skip})
        candidates = [
            parsed
            for record in (page.get("data") or [])
            if isinstance(record, dict) and (parsed := _parse(record)) is not None
        ]
        if not candidates:
            logger.info("Cleveland page at skip=%d held no displayable artwork", skip)
            return None
        return self._rng.choice(candidates)

    async def get(self, artwork_id: int) -> SourceArtwork | None:
        """One artwork by id. None when Cleveland does not have it, or cannot show it."""
        try:
            payload = await self._get(f"/artworks/{artwork_id}", {})
        except SourceError as exc:
            if "returned 404" in str(exc):
                return None
            raise
        record = payload.get("data")
        return _parse(record) if isinstance(record, dict) else None

    async def artwork_types(self) -> list[SourceFilter]:
        """The offered types with live totals, asked once and then cached.

        Ten requests, at most once an hour, and only when somebody opens the settings panel
        with Cleveland selected. A type the museum reports nothing for is dropped rather
        than shown at zero: there is no dependent-count machinery here to make a zero mean
        something, so a zero would just be a filter that does not work.
        """
        async with self._filters_lock:
            fresh = (
                self._filters is not None
                and asyncio.get_running_loop().time() - self._filters_at < FILTER_CACHE_SECONDS
            )
            if self._filters is not None and fresh:
                return self._filters

            counted = await asyncio.gather(
                *(self._count_of(value) for value in OFFERED_TYPES), return_exceptions=True
            )
            offers: list[SourceFilter] = []
            for value, result in zip(OFFERED_TYPES, counted, strict=True):
                if isinstance(result, BaseException):
                    logger.warning("Could not count Cleveland type %r: %s", value, result)
                    continue
                if result > 0:
                    offers.append(SourceFilter(value=value, label=value, count=result))
            offers.sort(key=lambda offer: -offer.count)
            self._filters = offers
            self._filters_at = asyncio.get_running_loop().time()
            return offers

    async def _count_of(self, artwork_type: str) -> int:
        payload = await self._get("/artworks/", {"limit": 1, "skip": 0, "type": artwork_type})
        return int((payload.get("info") or {}).get("total") or 0)


# --- parsing ----------------------------------------------------------------------


def _parse(record: dict[str, Any]) -> SourceArtwork | None:
    """One CMA record to a domain `Artwork`, or None when it cannot be displayed.

    Returning None rather than raising: a record without a usable image is ordinary — the
    `has_image` flag covers the images block existing, not `web` being present in it — and
    one bad record in a page of ten should cost that record, not the page.
    """
    artwork_id = record.get("id")
    if not isinstance(artwork_id, int):
        return None
    image = _web_image(record.get("images"))
    if image is None:
        return None
    url, width, height = image

    return SourceArtwork(
        artwork=Artwork(
            id=artwork_id,
            title=record.get("title") or None,
            artist_title=_artist(record.get("creators")),
            artist_display=_artist_display(record.get("creators")),
            date_display=record.get("creation_date") or None,
            medium_display=record.get("technique") or None,
            credit_line=record.get("creditline") or None,
            department_title=record.get("department") or None,
            place_of_origin=_culture(record.get("culture")),
            artwork_type_title=record.get("type") or None,
            main_reference_number=record.get("accession_number") or None,
            description=record.get("description") or None,
            # The image id is the accession number, which is what the URL is built around.
            # Nothing here uses it to build one — `image_url` is already finished — but the
            # response shape requires it and an empty string would read as a bug.
            image_id=str(record.get("accession_number") or artwork_id),
            # `share_license_status == "CC0"` is the per-record licence fact, and it is
            # already in the query. Re-checking it here is the belt to that braces: this is
            # the one flag ADR-0007 makes non-negotiable, and a parameter silently ignored
            # upstream would otherwise put a copyrighted work on screen.
            is_public_domain=record.get("share_license_status") == "CC0",
            # Cleveland's own curatorial signal, and the one field that maps cleanly onto
            # AIC's. Nothing scores a Cleveland artwork yet, so this is carried rather than
            # used — but dropping it here would be the harder thing to notice later.
            is_boosted=bool(record.get("is_highlight")),
            # No `lqip`, no `alt_text`: the two absences the overlay and the AI path each
            # have to handle. Width and height are real and are worth carrying — the
            # display uses them for nothing yet, and a scoring pass would want them.
            thumbnail=Thumbnail(width=width, height=height),
        ),
        image_url=url,
    )


def _web_image(images: Any) -> tuple[str, int | None, int | None] | None:
    """The `web` derivative: 900px on the long edge, and the only one worth showing.

    `print` is 3400px and several megabytes, which is a slow first paint on a display that
    changes picture every few minutes; `full` is a TIFF no browser will render. So there is
    one usable size rather than the ladder AIC offers, and `chooseWidth()` has nothing to
    choose — ADR-0012 item 3, arrived at.
    """
    if not isinstance(images, dict):
        return None
    web = images.get("web")
    if not isinstance(web, dict):
        return None
    url = web.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    return url, _as_int(web.get("width")), _as_int(web.get("height"))


def _as_int(value: Any) -> int | None:
    """CMA reports image dimensions as strings. `"900"`, not `900`."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _artist(creators: Any) -> str | None:
    """The first creator's name, without the nationality and dates."""
    display = _artist_display(creators)
    return _ARTIST_SUFFIX.sub("", display).strip() or None if display else None


def _artist_display(creators: Any) -> str | None:
    """The first creator exactly as Cleveland writes it, parenthetical included."""
    if not isinstance(creators, list) or not creators:
        return None
    first = creators[0]
    if not isinstance(first, dict):
        return None
    description = first.get("description")
    return description.strip() if isinstance(description, str) and description.strip() else None


def _culture(culture: Any) -> str | None:
    """`culture` is a list — `["Italy, 18th century"]`. Joined, because the overlay has one
    line for where a work is from and Cleveland occasionally names two places."""
    if not isinstance(culture, list):
        return None
    parts = [item.strip() for item in culture if isinstance(item, str) and item.strip()]
    return "; ".join(parts) or None
