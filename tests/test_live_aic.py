"""Live tests against the real AIC API and IIIF service.

Excluded from the default run and from CI. Run by hand when a contract test starts looking
suspicious, before a release, or to refresh the recorded fixtures:

    uv run pytest -m live

These are the tests that catch API drift, which is the failure this project is most
exposed to.
"""

import httpx
import pytest

from app.core.config import Settings
from app.domain.artwork import iiif_url
from app.providers.aic.client import AicClient

pytestmark = pytest.mark.live

BASE = "https://api.artic.edu/api/v1"


@pytest.fixture
def live_settings() -> Settings:
    return Settings()


@pytest.fixture
async def live_client(live_settings):
    client = AicClient(live_settings)
    yield client
    await client.aclose()


class TestLiveApi:
    async def test_random_artwork_is_public_domain_and_has_an_image(self, live_client):
        result = await live_client.random_displayable()
        assert result is not None
        artwork, iiif_base = result
        assert artwork.is_public_domain
        assert artwork.image_id
        assert iiif_base.startswith("https://")

    async def test_the_fields_the_docs_claim_are_still_there(self, live_client):
        artwork = await live_client.get(27992)
        assert artwork is not None
        assert artwork.thumbnail is not None
        assert artwork.thumbnail.lqip
        assert artwork.thumbnail.alt_text
        assert artwork.color is not None, "docs/aic-api.md records `color` as confirmed"

    async def test_search_still_refuses_past_one_thousand_records(self, live_settings):
        # If this starts passing, AIC raised the cap and docs/aic-api.md is stale.
        async with httpx.AsyncClient(
            base_url=BASE, headers={"AIC-User-Agent": live_settings.aic_user_agent}
        ) as raw:
            ok = await raw.get(
                "/artworks/search", params={"limit": 100, "page": 10, "fields": "id"}
            )
            past = await raw.get(
                "/artworks/search", params={"limit": 100, "page": 11, "fields": "id"}
            )
        assert ok.status_code == 200
        assert past.status_code == 403

    async def test_the_listing_endpoint_is_still_uncapped(self, live_settings):
        # This is what build_index.py depends on. ADR-0003 postscript.
        async with httpx.AsyncClient(
            base_url=BASE, headers={"AIC-User-Agent": live_settings.aic_user_agent}
        ) as raw:
            deep = await raw.get("/artworks", params={"limit": 100, "page": 1000, "fields": "id"})
        assert deep.status_code == 200
        assert deep.json()["data"]


class TestLiveImages:
    async def test_hotlinking_is_still_blocked(self, live_client):
        """Asserts the premise of ADR-0008.

        If this starts failing, Cloudflare stopped challenging plain image requests, the
        proxy fallback became dead code, and ADR-0008 should be revisited.
        """
        url = iiif_url("https://www.artic.edu/iiif/2", "2d484387-2509-5e8e-2c43-22f9981972eb")
        async with httpx.AsyncClient(timeout=30) as raw:
            response = await raw.get(url, headers={"User-Agent": "Mozilla/5.0"})
        assert response.status_code == 403
        assert response.headers.get("cf-mitigated") == "challenge"

    async def test_the_proxy_path_can_fetch_an_image(self, live_client):
        response = await live_client.fetch_image(
            "https://www.artic.edu/iiif/2", "2d484387-2509-5e8e-2c43-22f9981972eb", 843
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert len(response.content) > 10_000
