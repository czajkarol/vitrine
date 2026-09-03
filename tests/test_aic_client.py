"""Contract tests for the AIC client, against recorded real responses.

These are what tell us AIC renamed a field. respx intercepts httpx, so nothing leaves the
machine.
"""

import random

import httpx
import pytest
import respx

from app.providers.aic.client import AicClient, AicError, AicUnavailableError

BASE = "https://api.artic.edu/api/v1"


@pytest.fixture
async def client(settings):
    aic = AicClient(settings, rng=random.Random(0))
    yield aic
    await aic.aclose()


class TestParsingRecordedResponses:
    @respx.mock
    async def test_parses_a_real_search_response(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        page = await client.search_public_domain(limit=10, page=1)

        assert page.artworks, "recorded fixture should contain artworks"
        assert page.iiif_base == "https://www.artic.edu/iiif/2"
        first = page.artworks[0]
        assert first.id > 0
        assert first.title

    @respx.mock
    async def test_every_record_in_the_public_domain_fixture_is_public_domain(
        self, client, search_response
    ):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        page = await client.search_public_domain(limit=10, page=1)
        assert all(a.is_public_domain for a in page.artworks)

    @respx.mock
    async def test_parses_the_fields_the_display_depends_on(self, client, detail_response):
        respx.get(f"{BASE}/artworks/27992").mock(
            return_value=httpx.Response(200, json=detail_response)
        )
        artwork = await client.get(27992)

        assert artwork is not None
        assert artwork.title
        assert artwork.image_id
        assert artwork.is_public_domain
        # Confirmed live 2026-09-03; the display and the tint both rely on these.
        assert artwork.thumbnail is not None
        assert artwork.thumbnail.lqip and artwork.thumbnail.lqip.startswith("data:image/gif")
        assert artwork.thumbnail.alt_text
        assert artwork.thumbnail.width and artwork.thumbnail.height
        assert artwork.color is not None
        assert 0 <= artwork.color.h <= 360

    @respx.mock
    async def test_a_record_without_an_image_is_not_displayable(self, client, no_image_response):
        # Roughly 55% of the collection has no image_id. It must be skipped, not crash.
        respx.get(f"{BASE}/artworks/117474").mock(
            return_value=httpx.Response(200, json=no_image_response)
        )
        artwork = await client.get(117474)
        assert artwork is not None
        assert artwork.image_id is None
        assert not artwork.is_displayable


class TestRequestShape:
    @respx.mock
    async def test_sends_the_courtesy_header_on_every_request(self, client, search_response):
        route = respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        await client.search_public_domain()
        assert route.calls.last.request.headers["AIC-User-Agent"].startswith("vitrine-tests")

    @respx.mock
    async def test_requests_explicit_fields_and_the_public_domain_filter(
        self, client, search_response
    ):
        route = respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        await client.search_public_domain()
        url = route.calls.last.request.url
        # Without fields=, the response carries neither image_id nor is_public_domain,
        # which makes the hard filter impossible to apply.
        assert "image_id" in str(url)
        assert "is_public_domain" in str(url)

    async def test_refuses_to_exceed_the_search_record_cap(self, client):
        # page * limit must stay <= 1000; AIC answers 403 past it.
        with pytest.raises(ValueError, match="search cap"):
            await client.search_public_domain(limit=100, page=11)


class TestFailurePaths:
    @respx.mock
    async def test_retries_a_500_then_succeeds(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, json=search_response),
            ]
        )
        page = await client.search_public_domain()
        assert page.artworks

    @respx.mock
    async def test_gives_up_after_repeated_failures(self, client):
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(503))
        with pytest.raises(AicUnavailableError):
            await client.search_public_domain()

    @respx.mock
    async def test_retries_a_timeout(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            side_effect=[
                httpx.ConnectTimeout("timed out"),
                httpx.Response(200, json=search_response),
            ]
        )
        page = await client.search_public_domain()
        assert page.artworks

    @respx.mock
    async def test_does_not_retry_a_400(self, client):
        route = respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(400))
        with pytest.raises(AicError):
            await client.search_public_domain()
        assert route.call_count == 1, "a 400 is our bug; retrying just repeats it"

    @respx.mock
    async def test_unknown_artwork_returns_none(self, client):
        respx.get(f"{BASE}/artworks/999999999").mock(return_value=httpx.Response(404))
        assert await client.get(999999999) is None

    @respx.mock
    async def test_missing_iiif_url_is_an_error_not_a_guess(self, client, search_response):
        payload = {**search_response, "config": {}}
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(200, json=payload))
        # Hardcoding a fallback base would paper over exactly the AIC change we want to see.
        with pytest.raises(AicError, match="iiif_url"):
            await client.search_public_domain()


class TestRandomSelection:
    @respx.mock
    async def test_returns_only_displayable_artworks(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        result = await client.random_displayable()
        assert result is not None
        artwork, iiif_base = result
        assert artwork.is_displayable
        assert iiif_base == "https://www.artic.edu/iiif/2"

    @respx.mock
    async def test_returns_none_when_nothing_is_displayable(self, client, search_response):
        stripped = {
            **search_response,
            "data": [{**r, "image_id": None} for r in search_response["data"]],
        }
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(200, json=stripped))
        assert await client.random_displayable() is None
