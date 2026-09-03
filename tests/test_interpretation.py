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
from app.domain.interpretation import CacheKey
from app.main import create_app
from app.providers.ai.base import (
    InvalidResponseError,
    ProviderUnavailableError,
    TokenUsage,
)
from app.providers.ai.mock import MockProvider
from app.providers.aic.client import AicClient
from app.repositories.ai_usage import AiUsageRepository
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.repositories.interpretations import NullSharedCache, SqliteInterpretationCache
from app.services.fallback import FallbackSet
from app.services.interpretation import (
    ArtworkNotFoundError,
    BudgetExhaustedError,
    CircuitOpenError,
    InterpretationService,
)

BASE = "https://api.artic.edu/api/v1"

OTHER = Artwork(
    id=27993,
    title="Another work",
    is_public_domain=True,
    image_id="def",
)

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
        local_cache=SqliteInterpretationCache(database),
        shared_cache=NullSharedCache(),
        usage=AiUsageRepository(database),
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
            local_cache=SqliteInterpretationCache(database),
            shared_cache=NullSharedCache(),
            usage=AiUsageRepository(database),
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
            "circuit_open": False,
        }


class TestTheCacheChain:
    async def test_a_second_request_does_not_reach_the_provider(self, settings):
        provider = MockProvider()
        service = _service(settings, provider=provider, artworks=(INDEXED,))

        first = await service.interpret(27992, "en")
        second = await service.interpret(27992, "en")

        assert first == second
        # The whole point of the cache, and the only way to see it from outside.
        assert provider.calls == 1

    async def test_each_language_is_cached_separately(self, settings):
        provider = MockProvider()
        service = _service(settings, provider=provider, artworks=(INDEXED,))

        await service.interpret(27992, "en")
        await service.interpret(27992, "pl")
        assert provider.calls == 2

    async def test_a_different_model_does_not_reuse_the_entry(self, settings):
        artworks = (INDEXED,)
        first = _service(settings, provider=MockProvider(model="mock-1"), artworks=artworks)
        await first.interpret(27992, "en")

        second_provider = MockProvider(model="mock-2")
        second = _service(settings, provider=second_provider, artworks=artworks)
        await second.interpret(27992, "en")
        # Two providers answering the same question do not produce interchangeable text,
        # so an entry from one must not be served as though it came from the other.
        assert second_provider.calls == 1

    async def test_a_new_prompt_version_invalidates_the_entry(self, settings, monkeypatch):
        from app.services import interpretation as service_module

        provider = MockProvider()
        service = _service(settings, provider=provider, artworks=(INDEXED,))
        await service.interpret(27992, "en")

        monkeypatch.setattr(service_module, "PROMPT_VERSION", 99)
        await service.interpret(27992, "en")
        assert provider.calls == 2

    async def test_a_corrupt_row_is_a_miss_rather_than_a_failure(self, settings):
        provider = MockProvider()
        service = _service(settings, provider=provider, artworks=(INDEXED,))
        await service.interpret(27992, "en")

        database = Database(settings.database_path)
        with database.connect() as connection:
            connection.execute("UPDATE interpretations SET payload_json = '{\"nope\": 1}'")

        # Validated on the way out: a row that no longer fits the shape must not reach the
        # display, and must not take the request down either.
        assert await service.interpret(27992, "en") is not None
        assert provider.calls == 2

    async def test_a_cache_that_raises_is_skipped(self, settings):
        class ExplodingCache:
            name = "exploding"

            async def get(self, key):
                raise RuntimeError("disk on fire")

            async def put(self, key, value):
                raise RuntimeError("disk still on fire")

        database = Database(settings.database_path)
        database.migrate()
        index = ArtworkIndexRepository(database)
        index.upsert_many_sync([INDEXED])
        provider = MockProvider()
        service = InterpretationService(
            provider=provider,
            index=index,
            fallback=FallbackSet(),
            client=_aic(settings),
            settings=settings,
            local_cache=ExplodingCache(),
            shared_cache=NullSharedCache(),
            usage=AiUsageRepository(database),
        )

        # A cache is an optimisation. Losing it costs a provider call, not the feature.
        assert (await service.interpret(27992, "en")) is not None
        assert provider.calls == 1

    async def test_the_shared_tier_is_consulted_and_always_misses(self, settings):
        shared = NullSharedCache()
        assert (
            await shared.get(
                CacheKey(
                    artwork_id=1, language="en", provider="mock", model="mock-1", prompt_version=1
                )
            )
            is None
        )


class TestTheBudget:
    async def test_records_what_each_call_cost(self, settings):
        service = _service(settings, artworks=(INDEXED,))
        await service.interpret(27992, "en")

        usage = AiUsageRepository(Database(settings.database_path))
        assert usage.requests_today_sync("mock") == 1
        totals = usage.totals_sync()["mock"]
        assert totals["tokens_in"] > 0 and totals["tokens_out"] > 0

    async def test_a_cache_hit_costs_nothing_and_is_not_counted(self, settings):
        service = _service(settings, artworks=(INDEXED,))
        await service.interpret(27992, "en")
        await service.interpret(27992, "en")

        # The budget limits what we spend, not what we serve.
        assert AiUsageRepository(Database(settings.database_path)).requests_today_sync("mock") == 1

    async def test_refuses_once_the_daily_cap_is_reached(self, settings):
        capped = settings.model_copy(update={"ai_daily_request_limit": 2})
        provider = MockProvider()
        service = _service(capped, provider=provider, artworks=(INDEXED, OTHER))

        await service.interpret(27992, "en")
        await service.interpret(27992, "pl")
        with pytest.raises(BudgetExhaustedError):
            await service.interpret(OTHER.id, "en")
        # Checked before the call, not reconciled after it.
        assert provider.calls == 2

    async def test_an_already_cached_answer_survives_a_spent_budget(self, settings):
        capped = settings.model_copy(update={"ai_daily_request_limit": 1})
        service = _service(capped, artworks=(INDEXED, OTHER))

        await service.interpret(27992, "en")
        with pytest.raises(BudgetExhaustedError):
            await service.interpret(OTHER.id, "en")

        # Nothing is being spent to serve this, so refusing it would be a limit on the
        # display rather than on the bill.
        assert await service.interpret(27992, "en") is not None

    async def test_a_zero_limit_stops_everything(self, settings):
        stopped = settings.model_copy(update={"ai_daily_request_limit": 0})
        provider = MockProvider()
        service = _service(stopped, provider=provider, artworks=(INDEXED,))
        with pytest.raises(BudgetExhaustedError):
            await service.interpret(27992, "en")
        assert provider.calls == 0

    async def test_yesterdays_spending_does_not_count(self, settings):
        from datetime import date, timedelta

        capped = settings.model_copy(update={"ai_daily_request_limit": 1})
        database = Database(capped.database_path)
        database.migrate()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        AiUsageRepository(database).record_sync("mock", TokenUsage(), day=yesterday)

        service = _service(capped, artworks=(INDEXED,))
        # The cap is daily. Spending it yesterday must not spend it again today.
        assert await service.interpret(27992, "en") is not None

    def test_a_spent_budget_reads_differently_from_a_broken_provider(self, ai_settings, tmp_path):
        spent = ai_settings.model_copy(update={"ai_daily_request_limit": 0})
        with TestClient(create_app(spent)) as client:
            index = ArtworkIndexRepository(Database(spent.database_path))
            index.upsert_many_sync([INDEXED])
            response = client.get("/api/interpretation/27992")
            assert response.status_code == 503
            # The display says something different about a decision than about a fault.
            assert response.json()["detail"] == "ai_budget_exhausted"


class TestTheCircuitBreaker:
    async def test_stops_calling_a_provider_that_keeps_failing(self, settings):
        wired = settings.model_copy(update={"ai_circuit_breaker_threshold": 2})
        provider = MockProvider(fail_with=ProviderUnavailableError("down"))
        service = _service(wired, provider=provider, artworks=(INDEXED,))

        for _ in range(2):
            with pytest.raises(ProviderUnavailableError):
                await service.interpret(27992, "en")

        with pytest.raises(CircuitOpenError):
            await service.interpret(27992, "en")
        # The third request never reached the provider, which is the entire point: each
        # attempt would otherwise cost a timeout the viewer waits through.
        assert provider.calls == 2
        assert service.circuit_open is True

    async def test_an_unparseable_response_counts_as_a_failure(self, settings):
        wired = settings.model_copy(update={"ai_circuit_breaker_threshold": 1})
        provider = MockProvider(fail_with=InvalidResponseError("prose, not JSON"))
        service = _service(wired, provider=provider, artworks=(INDEXED,))

        with pytest.raises(InvalidResponseError):
            await service.interpret(27992, "en")
        # A provider that has started returning prose where JSON was asked for is not
        # healthy, and retrying it every time costs money for nothing.
        assert service.circuit_open is True

    async def test_a_spent_budget_does_not_open_the_circuit(self, settings):
        wired = settings.model_copy(
            update={"ai_daily_request_limit": 0, "ai_circuit_breaker_threshold": 1}
        )
        service = _service(wired, artworks=(INDEXED,))

        with pytest.raises(BudgetExhaustedError):
            await service.interpret(27992, "en")
        # The provider did nothing wrong. Refusing to spend is our decision, not its fault.
        assert service.circuit_open is False

    async def test_the_cache_still_answers_while_the_circuit_is_open(self, settings):
        wired = settings.model_copy(update={"ai_circuit_breaker_threshold": 1})
        service = _service(wired, artworks=(INDEXED, OTHER))
        await service.interpret(27992, "en")

        service._provider = MockProvider(fail_with=ProviderUnavailableError("down"))
        with pytest.raises(ProviderUnavailableError):
            await service.interpret(OTHER.id, "en")
        assert service.circuit_open is True

        # "Answer from cache only" is the whole instruction in docs/ai-system.md — an open
        # circuit must not take away what has already been paid for.
        assert await service.interpret(27992, "en") is not None

    def test_health_reports_an_open_circuit(self, ai_settings):
        wired = ai_settings.model_copy(update={"ai_circuit_breaker_threshold": 1})
        with TestClient(create_app(wired)) as client:
            client.app.state.interpretation._provider = MockProvider(
                fail_with=ProviderUnavailableError("down")
            )
            index = ArtworkIndexRepository(Database(wired.database_path))
            index.upsert_many_sync([INDEXED])

            assert client.get("/api/interpretation/27992").status_code == 503
            ai = client.get("/api/health").json()["ai"]
            # Still "enabled" — that says what is configured. `circuit_open` says whether
            # it is currently being called.
            assert ai["enabled"] is True
            assert ai["circuit_open"] is True
