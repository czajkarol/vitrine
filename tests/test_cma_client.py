"""Contract tests for the Cleveland client, against recorded real responses.

Same rule as the AIC fixtures: these are captured responses, not hand-written dicts. A
hand-written fixture would test our idea of Cleveland's API, and the point of ADR-0012 was
that our idea of it was wrong on two of five columns.

What is asserted here is the two things that make this source *different* from AIC and are
therefore easy to get wrong: it has no IIIF, so the URL arrives finished; and it is missing
`lqip`, `alt_text` and `color`, so every one of those has to come back as an absence the
display can handle rather than as something that throws.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.providers.cma.client import BASE_URL, CmaClient
from app.providers.source import SourceError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cma"

pytestmark = pytest.mark.anyio


def load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def page() -> dict:
    return load("artworks_page.json")


@pytest.fixture
def detail() -> dict:
    return load("artwork_detail.json")


@pytest.fixture
def client(settings: Settings) -> CmaClient:
    return CmaClient(settings)


class TestParsing:
    @respx.mock
    async def test_it_returns_a_finished_image_url_and_no_iiif_base(self, client, page):
        """The one structural difference from AIC. Cleveland has three fixed URLs per
        record and no IIIF service, so there is no base to remember and no width to pick."""
        respx.get(f"{BASE_URL}/artworks/").mock(return_value=httpx.Response(200, json=page))

        result = await client.random()

        assert result is not None
        assert result.iiif_base == ""
        assert result.image_url is not None
        assert result.image_url.startswith("https://openaccess-cdn.clevelandart.org/")
        # `_web`, not `_print`: 3400px and several megabytes is a slow first paint on a
        # display that changes picture every few minutes.
        assert "_web.jpg" in result.image_url

    @respx.mock
    async def test_the_three_missing_fields_come_back_absent_rather_than_throwing(
        self, client, page
    ):
        """ADR-0012's decisive finding, and ADR-0013's accepted cost. Each of these is a
        feature at AIC — the crossfade's blur, the screen reader's text and the AI prompt's
        grounding, and the overlay scrim — and each has to degrade rather than fail."""
        respx.get(f"{BASE_URL}/artworks/").mock(return_value=httpx.Response(200, json=page))

        artwork = (await client.random()).artwork

        assert artwork.thumbnail is not None
        assert artwork.thumbnail.lqip is None
        assert artwork.thumbnail.alt_text is None
        assert artwork.color is None

    @respx.mock
    async def test_it_keeps_the_dimensions_cleveland_reports_as_strings(self, client, page):
        """`"900"`, not `900`. Carried through as integers or a scoring pass would compare
        a string to a number and be wrong without saying so."""
        respx.get(f"{BASE_URL}/artworks/").mock(return_value=httpx.Response(200, json=page))

        thumbnail = (await client.random()).artwork.thumbnail

        assert isinstance(thumbnail.width, int)
        assert thumbnail.width > 0

    @respx.mock
    async def test_the_artist_loses_the_nationality_and_dates(self, client, detail):
        """`creators[].description` reads "Piranesi (Italian, 1720-1778)". AIC's equivalent
        field carries the name alone, and the overlay is written for that."""
        respx.get(f"{BASE_URL}/artworks/95343").mock(return_value=httpx.Response(200, json=detail))

        artwork = (await client.get(95343)).artwork

        if artwork.artist_display:
            assert "(" in artwork.artist_display
            assert "(" not in (artwork.artist_title or "")

    @respx.mock
    async def test_every_parsed_record_is_public_domain(self, client, page):
        """ADR-0007's hard filter, checked on the way out as well as asked for in the
        query. A parameter silently ignored upstream would otherwise put a copyrighted
        work on screen, and that is the one failure that is not recoverable."""
        respx.get(f"{BASE_URL}/artworks/").mock(return_value=httpx.Response(200, json=page))

        for _ in range(5):
            assert (await client.random()).artwork.is_displayable

    async def test_a_record_with_no_web_image_is_skipped_not_raised(self, client):
        """`has_image` covers the images block existing, not `web` being present in it."""
        from app.providers.cma.client import _parse

        only_print = {"print": {"url": "https://x/y.jpg"}}
        assert _parse({"id": 1, "title": "x", "images": only_print}) is None
        assert _parse({"id": 1, "title": "x", "images": None}) is None
        assert _parse({"title": "no id"}) is None


class TestFilters:
    @respx.mock
    async def test_counts_come_from_the_museum_rather_than_being_guessed(self, client):
        respx.get(f"{BASE_URL}/artworks/").mock(
            return_value=httpx.Response(200, json={"info": {"total": 3956}, "data": []})
        )

        offers = await client.artwork_types()

        assert offers
        assert all(offer.count == 3956 for offer in offers)

    @respx.mock
    async def test_a_type_the_museum_has_nothing_for_is_not_offered(self, client):
        """There is no dependent-count machinery here to make a zero mean something, so a
        zero would just be a filter that does not work."""
        respx.get(f"{BASE_URL}/artworks/").mock(
            return_value=httpx.Response(200, json={"info": {"total": 0}, "data": []})
        )

        assert await client.artwork_types() == []

    @respx.mock
    async def test_the_counts_are_asked_for_once(self, client):
        """Ten requests are cheap once and silly every time the settings panel opens."""
        route = respx.get(f"{BASE_URL}/artworks/").mock(
            return_value=httpx.Response(200, json={"info": {"total": 10}, "data": []})
        )

        await client.artwork_types()
        first = route.call_count
        await client.artwork_types()

        assert route.call_count == first


class TestFailure:
    @respx.mock
    async def test_a_transport_failure_becomes_a_source_error(self, client):
        """No httpx exception type may surface above `providers/`."""
        respx.get(f"{BASE_URL}/artworks/").mock(side_effect=httpx.ConnectError("down"))

        with pytest.raises(SourceError):
            await client.random()

    @respx.mock
    async def test_a_server_error_becomes_a_source_error(self, client):
        respx.get(f"{BASE_URL}/artworks/").mock(return_value=httpx.Response(503))

        with pytest.raises(SourceError):
            await client.random()

    @respx.mock
    async def test_an_unknown_id_is_none_rather_than_an_error(self, client):
        respx.get(f"{BASE_URL}/artworks/999999999").mock(return_value=httpx.Response(404))

        assert await client.get(999999999) is None

    @respx.mock
    async def test_an_empty_collection_is_none_rather_than_an_error(self, client):
        respx.get(f"{BASE_URL}/artworks/").mock(
            return_value=httpx.Response(200, json={"info": {"total": 0}, "data": []})
        )

        assert await client.random() is None
