"""Integration tests for the HTTP routes, with AIC intercepted by respx."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

BASE = "https://api.artic.edu/api/v1"
IIIF = "https://www.artic.edu/iiif/2"
IMAGE_ID = "2d484387-2509-5e8e-2c43-22f9981972eb"


def _page_from(search_response) -> list:
    """The indexable artworks in a recorded search response."""
    from app.domain.artwork import Artwork
    from app.domain.indexing import is_indexable

    artworks = [Artwork.model_validate(r) for r in search_response["data"]]
    return [a for a in artworks if is_indexable(a)]


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class TestRandomArtwork:
    @respx.mock
    def test_returns_a_public_domain_artwork(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        response = client.get("/api/artwork/random")
        assert response.status_code == 200

        body = response.json()
        assert body["id"] > 0
        assert body["title"]
        assert body["image_id"]
        assert body["iiif_base"] == IIIF

    @respx.mock
    def test_carries_the_fields_the_transition_pipeline_needs(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        body = client.get("/api/artwork/random").json()
        # lqip is painted immediately; alt_text is the accessible description.
        assert body["lqip"].startswith("data:image/gif")
        assert body["alt_text"]

    @respx.mock
    def test_falls_back_to_the_bundled_set_when_aic_is_down(self, client):
        # docs/product-spec.md: an unreachable API degrades to the bundled set, not to an
        # error. The response says which tier answered so the UI can say so quietly.
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(503))
        response = client.get("/api/artwork/random")
        assert response.status_code == 200

        body = response.json()
        assert body["source"] == "fallback"
        assert body["image_id"]
        assert body["iiif_base"]

    @respx.mock
    def test_reports_503_when_every_tier_is_empty(self, no_fallback_set, client):
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(503))
        response = client.get("/api/artwork/random")
        assert response.status_code == 503
        assert response.json()["detail"] == "aic_unavailable"

    @respx.mock
    def test_skips_works_that_are_not_public_domain(self, no_fallback_set, client, search_response):
        stripped = {
            **search_response,
            "data": [{**r, "is_public_domain": False} for r in search_response["data"]],
        }
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(200, json=stripped))
        response = client.get("/api/artwork/random")
        # Nothing eligible anywhere: the hard public-domain filter (ADR-0007) wins over
        # showing something.
        assert response.status_code == 503

    @respx.mock
    def test_prefers_the_local_index_over_calling_aic(self, client, search_response, database):
        from app.repositories.artwork_index import ArtworkIndexRepository
        from app.repositories.preferences import PreferencesRepository
        from app.services.selection import IIIF_BASE_KEY

        page = _page_from(search_response)
        ArtworkIndexRepository(database).upsert_many_sync(page)
        PreferencesRepository(database).set_sync(IIIF_BASE_KEY, IIIF)

        route = respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        response = client.get("/api/artwork/random")

        assert response.status_code == 200
        assert response.json()["source"] == "index"
        # ADR-0003: selection reads SQLite, never the network.
        assert not route.called


class TestImageProxy:
    @respx.mock
    def test_serves_image_bytes(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        respx.get(f"{IIIF}/{IMAGE_ID}/full/843,/0/default.jpg").mock(
            return_value=httpx.Response(
                200, content=b"\xff\xd8\xff-jpeg-bytes", headers={"content-type": "image/jpeg"}
            )
        )
        # The proxy learns the IIIF base from a prior artwork response rather than
        # accepting one from the caller.
        client.get("/api/artwork/random")

        response = client.get(f"/api/image/{IMAGE_ID}?w=843")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == b"\xff\xd8\xff-jpeg-bytes"

    @respx.mock
    def test_sends_both_headers_cloudflare_requires(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        route = respx.get(f"{IIIF}/{IMAGE_ID}/full/843,/0/default.jpg").mock(
            return_value=httpx.Response(200, content=b"x", headers={"content-type": "image/jpeg"})
        )
        client.get("/api/artwork/random")
        client.get(f"/api/image/{IMAGE_ID}?w=843")

        headers = route.calls.last.request.headers
        # Either header alone gets a 403 challenge. See ADR-0008.
        assert headers["AIC-User-Agent"]
        assert "Mozilla" in headers["User-Agent"]

    def test_rejects_a_malformed_image_id(self, client):
        # Keeps the endpoint from being coaxed into fetching arbitrary paths.
        response = client.get("/api/image/not-a-uuid?w=843")
        assert response.status_code == 400
        assert response.json()["detail"] == "malformed_image_id"

    def test_rejects_a_width_off_the_cached_ladder(self, client):
        response = client.get(f"/api/image/{IMAGE_ID}?w=999")
        assert response.status_code == 400
        assert response.json()["detail"] == "unsupported_width"

    def test_reports_503_before_any_iiif_base_is_known(self, no_fallback_set, client):
        # A fresh install: nothing has taught us a IIIF base yet, and we will not invent
        # one (CLAUDE.md).
        response = client.get(f"/api/image/{IMAGE_ID}?w=843")
        assert response.status_code == 503

    @respx.mock
    def test_reports_502_when_the_image_is_gone(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        respx.get(f"{IIIF}/{IMAGE_ID}/full/843,/0/default.jpg").mock(
            return_value=httpx.Response(404)
        )
        client.get("/api/artwork/random")
        response = client.get(f"/api/image/{IMAGE_ID}?w=843")
        assert response.status_code == 502


class TestPreferences:
    def test_defaults_before_anything_is_saved(self, client):
        body = client.get("/api/preferences").json()
        assert body["interval_minutes"] == 5

    def test_saves_and_reads_back(self, client):
        assert client.put("/api/preferences", json={"interval_minutes": 15}).status_code == 200
        assert client.get("/api/preferences").json()["interval_minutes"] == 15

    def test_rejects_an_interval_off_the_menu(self, client):
        # 1/5/15/30 only, per docs/product-spec.md.
        assert client.put("/api/preferences", json={"interval_minutes": 7}).status_code == 422

    def test_a_stored_value_we_no_longer_support_falls_back_to_the_default(self, client, settings):
        from app.repositories.database import Database
        from app.repositories.preferences import PreferencesRepository

        PreferencesRepository(Database(settings.database_path)).set_sync("interval_minutes", "99")
        # An interval retired from the menu must not become a 500 on every page load.
        assert client.get("/api/preferences").json()["interval_minutes"] == 5

    def test_does_not_expose_what_the_app_learned_for_itself(self, client, settings):
        from app.repositories.database import Database
        from app.repositories.preferences import PreferencesRepository

        PreferencesRepository(Database(settings.database_path)).set_sync("iiif_base", "http://x")
        # The preferences table also holds internal state; the browser sees only its own.
        assert set(client.get("/api/preferences").json()) == {"interval_minutes"}


class TestHealth:
    def test_health_does_not_call_aic(self, client):
        # respx is not active here: a call to AIC would raise instead of passing.
        assert client.get("/api/health").json() == {"status": "ok"}


class TestFrontend:
    def test_serves_the_display_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "vitrine" in response.text.lower()
