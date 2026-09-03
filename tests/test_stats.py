"""`/api/stats` and the counters behind it.

The counters are pure and are tested as arithmetic. The endpoint is tested for the thing
that actually goes wrong with a stats page: reporting numbers that did not move when the
work happened, or dividing by zero on a display nobody has touched yet.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.metrics import CacheTally, LatencySummary, Tally
from app.main import create_app

BASE = "https://api.artic.edu/api/v1"


class TestTally:
    def test_a_fresh_tally_has_no_rate_rather_than_a_division_by_zero(self):
        assert Tally().error_rate == 0.0

    def test_counts_errors_against_the_total(self):
        tally = Tally()
        tally.record()
        tally.record(error=True)
        assert (tally.total, tally.errors, tally.error_rate) == (2, 1, 0.5)


class TestCacheTally:
    def test_a_miss_is_not_an_error(self):
        """Separate type from Tally for exactly this reason: the first ask is meant to
        miss, and a metric that calls it a failure would read as a fault."""
        tally = CacheTally()
        tally.record(hit=False)
        assert (tally.hits, tally.misses, tally.hit_ratio) == (0, 1, 0.0)

    def test_ratio_is_hits_over_lookups(self):
        tally = CacheTally()
        tally.record(hit=True)
        tally.record(hit=True)
        tally.record(hit=False)
        assert tally.lookups == 3
        assert tally.hit_ratio == pytest.approx(2 / 3)


class TestLatencySummary:
    def test_keeps_a_mean_and_a_worst_case_without_the_samples(self):
        latency = LatencySummary()
        for elapsed in (100.0, 300.0, 200.0):
            latency.record(elapsed)
        assert latency.count == 3
        assert latency.average_ms == pytest.approx(200.0)
        assert latency.max_ms == 300.0

    def test_nothing_measured_averages_to_zero(self):
        assert LatencySummary().average_ms == 0.0


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class TestStatsEndpoint:
    def test_answers_before_anything_has_happened(self, client):
        """A display just switched on. Every rate is zero, and none of them is a 500."""
        body = client.get("/api/stats").json()
        assert body["uptime_seconds"] >= 0
        assert body["indexed_artworks"] == 0
        assert body["interpretation_cache"] == {"hits": 0, "misses": 0, "hit_ratio": 0.0}
        assert body["provider"]["calls"] == 0
        assert body["aic"] == {"requests": 0, "errors": 0, "error_rate": 0.0}
        assert body["usage"]["providers"] == {}

    @respx.mock
    def test_counts_aic_requests(self, client, search_response):
        respx.get(f"{BASE}/artworks/search").mock(
            return_value=httpx.Response(200, json=search_response)
        )
        client.get("/api/artwork/random")
        assert client.get("/api/stats").json()["aic"]["requests"] >= 1

    @respx.mock
    def test_counts_an_aic_failure_against_the_error_rate(self, client, no_fallback_set):
        respx.get(f"{BASE}/artworks/search").mock(return_value=httpx.Response(500))
        client.get("/api/artwork/random")

        aic = client.get("/api/stats").json()["aic"]
        assert aic["errors"] >= 1
        assert aic["error_rate"] > 0
        # One call the app made, however many attempts the client's own retries took.
        assert aic["errors"] <= aic["requests"]

    def test_reports_the_provider_that_is_actually_live(self, settings: Settings):
        configured = settings.model_copy(update={"ai_enabled": True, "ai_provider": "mock"})
        with TestClient(create_app(configured)) as client:
            provider = client.get("/api/stats").json()["provider"]
            assert provider["name"] == "mock"
            assert provider["model"]

    def test_a_generated_interpretation_moves_the_cache_and_latency_figures(
        self, settings: Settings, database
    ):
        """Ask twice: the first is a miss and a provider call, the second is a hit and
        is not. That relationship is the whole point of the cache figure."""
        from app.domain.artwork import Artwork, Thumbnail
        from app.repositories.artwork_index import ArtworkIndexRepository

        ArtworkIndexRepository(database).upsert_many_sync(
            [
                Artwork(
                    id=27992,
                    title="A work",
                    image_id="image-27992",
                    is_public_domain=True,
                    artwork_type_title="Painting",
                    thumbnail=Thumbnail(width=2000, height=1200, alt_text="A painting"),
                )
            ]
        )

        configured = settings.model_copy(update={"ai_enabled": True, "ai_provider": "mock"})
        with TestClient(create_app(configured)) as client:
            assert client.get("/api/interpretation/27992").status_code == 200
            first = client.get("/api/stats").json()
            assert first["interpretation_cache"]["misses"] == 1
            assert first["provider"]["calls"] == 1
            # A duration was measured, whatever it was. Asserting a number here would be
            # asserting the speed of the machine running the tests.
            assert first["provider"]["average_ms"] >= 0

            assert client.get("/api/interpretation/27992").status_code == 200
            second = client.get("/api/stats").json()
            assert second["interpretation_cache"]["hits"] == 1
            assert second["interpretation_cache"]["hit_ratio"] == 0.5
            assert second["provider"]["calls"] == 1, "a cache hit is not a provider call"

    def test_todays_usage_survives_a_restart(self, settings: Settings, database):
        """The one figure here that is not in memory, because it is the one the budget
        guard enforces against."""
        from app.providers.ai.base import TokenUsage
        from app.repositories.ai_usage import AiUsageRepository

        usage = TokenUsage(input_tokens=10, output_tokens=5)
        AiUsageRepository(database).record_sync("mock", usage)

        with TestClient(create_app(settings)) as client:
            usage = client.get("/api/stats").json()["usage"]
            assert usage["providers"]["mock"] == {
                "requests": 1,
                "tokens_in": 10,
                "tokens_out": 5,
            }
