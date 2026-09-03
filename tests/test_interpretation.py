"""Interpretation, end to end against the mock provider.

No network and no paid API, per `tests/CLAUDE.md`. The mock is the whole point of this
milestone's ordering: the path is proven before a vendor is attached to it.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.artwork import Artwork
from app.main import create_app
from app.providers.ai.base import ProviderUnavailableError
from app.providers.ai.mock import MockProvider
from app.providers.aic.client import AicClient
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.services.fallback import FallbackSet
from app.services.interpretation import ArtworkNotFoundError, InterpretationService

BASE = "https://api.artic.edu/api/v1"

INDEXED = Artwork(
    id=27992,
    title="Echizen",
    artist_title="Utagawa Hiroshige",
    is_public_domain=True,
    image_id="abc",
)


@pytest.fixture
def ai_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"ai_enabled": True, "ai_provider": "mock"})


@pytest.fixture
def ai_client(ai_settings: Settings):
    with TestClient(create_app(ai_settings)) as test_client:
        yield test_client


@pytest.fixture
def no_ai_client(settings: Settings):
    """The default configuration: no provider, which is a supported way to run."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _aic(settings: Settings) -> AicClient:
    return AicClient(settings)


def _service(
    settings: Settings,
    provider: MockProvider | None = None,
    artworks: tuple[Artwork, ...] = (),
    bundled: tuple[Artwork, ...] = (),
) -> InterpretationService:
    database = Database(settings.database_path)
    database.migrate()
    index = ArtworkIndexRepository(database)
    if artworks:
        index.upsert_many_sync(artworks)
    return InterpretationService(
        provider=provider or MockProvider(),
        index=index,
        fallback=FallbackSet(artworks=bundled),
        client=_aic(settings),
        settings=settings,
    )


class TestFindingTheArtwork:
    async def test_prefers_the_local_index(self, settings):
        service = _service(settings, artworks=(INDEXED,))
        # No respx here at all: reaching the network would raise rather than pass.
        assert (await service.find_artwork(27992)).title == "Echizen"

    async def test_falls_back_to_the_bundled_set(self, settings):
        # A fresh clone: no index built yet, and the bundled metadata is all there is.
        service = _service(settings, bundled=(INDEXED,))
        assert (await service.find_artwork(27992)).title == "Echizen"

    @respx.mock
    async def test_asks_aic_last(self, settings, detail_response):
        respx.get(f"{BASE}/artworks/27992").mock(
            return_value=httpx.Response(200, json=detail_response)
        )
        service = _service(settings)
        assert (await service.find_artwork(27992)) is not None

    @respx.mock
    async def test_an_unreachable_aic_reads_as_an_unknown_artwork(self, settings):
        respx.get(f"{BASE}/artworks/27992").mock(side_effect=httpx.ConnectError("down"))
        service = _service(settings)
        # Not the same situation, but the same outcome: there is nothing to interpret,
        # and the display keeps the museum facts it already has.
        with pytest.raises(ArtworkNotFoundError):
            await service.find_artwork(27992)


class TestInterpreting:
    async def test_returns_a_validated_interpretation(self, settings):
        service = _service(settings, artworks=(INDEXED,))
        result = await service.interpret(27992, "en")
        assert "Echizen" in result.visual_description
        assert 2 <= len(result.themes) <= 5

    async def test_answers_in_the_requested_language(self, settings):
        service = _service(settings, artworks=(INDEXED,))
        assert (await service.interpret(27992, "pl")).language == "pl"

    async def test_a_provider_failure_propagates_as_a_provider_error(self, settings):
        provider = MockProvider(fail_with=ProviderUnavailableError("down"))
        service = _service(settings, provider=provider, artworks=(INDEXED,))
        with pytest.raises(ProviderUnavailableError):
            await service.interpret(27992, "en")

    async def test_a_slow_provider_is_cut_off(self, settings):
        # Short by design: an interpretation that arrives after the artwork has rotated
        # away is not wanted, and an abandoned generation still costs money.
        impatient = settings.model_copy(update={"ai_timeout_seconds": 0.01})
        service = _service(
            impatient, provider=MockProvider(latency_seconds=0.5), artworks=(INDEXED,)
        )
        with pytest.raises(ProviderUnavailableError):
            await service.interpret(27992, "en")

    async def test_calling_it_with_no_provider_is_a_bug_not_a_state(self, settings):
        database = Database(settings.database_path)
        database.migrate()
        service = InterpretationService(
            provider=None,
            index=ArtworkIndexRepository(database),
            fallback=FallbackSet(artworks=(INDEXED,)),
            client=_aic(settings),
            settings=settings,
        )
        assert service.enabled is False
        # The route checks `enabled` and answers "ai_disabled". Getting here anyway is a
        # programming error, so it does not pretend to be a configuration state.
        with pytest.raises(RuntimeError):
            await service.interpret(27992, "en")


class TestInterpretationEndpoint:
    def test_reports_the_provider_alongside_the_text(self, ai_client, ai_settings):
        index = ArtworkIndexRepository(Database(ai_settings.database_path))
        index.upsert_many_sync([INDEXED])

        body = ai_client.get("/api/interpretation/27992?language=en").json()
        # The display labels this as generated, so the response says who generated it.
        assert body["provider"] == "mock"
        assert body["model"] == "mock-1"
        assert body["language"] == "en"
        assert body["themes"]

    def test_unknown_artwork_is_a_404(self, ai_client):
        with respx.mock:
            respx.get(f"{BASE}/artworks/999999").mock(return_value=httpx.Response(404))
            assert ai_client.get("/api/interpretation/999999").status_code == 404

    def test_rejects_a_language_the_app_cannot_display(self, ai_client):
        assert ai_client.get("/api/interpretation/27992?language=de").status_code == 422

    def test_says_ai_is_disabled_rather_than_erroring(self, no_ai_client):
        # The default configuration has no provider. This is an ordinary answer.
        response = no_ai_client.get("/api/interpretation/27992")
        assert response.status_code == 503
        assert response.json()["detail"] == "ai_disabled"

    def test_health_advertises_the_configured_provider(self, ai_client):
        assert ai_client.get("/api/health").json()["ai"] == {
            "enabled": True,
            "provider": "mock",
            "model": "mock-1",
        }
