"""The tier chain: local index, then AIC, then the bundled set (ADR-0003)."""

import random

import pytest

from app.domain.artwork import Artwork, Thumbnail
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.repositories.history import HistoryRepository
from app.repositories.preferences import PreferencesRepository
from app.services.fallback import FallbackSet
from app.services.selection import IIIF_BASE_KEY, SelectionService

IIIF = "https://www.artic.edu/iiif/2"


def _artwork(artwork_id: int) -> Artwork:
    return Artwork(
        id=artwork_id,
        title=f"Work {artwork_id}",
        image_id=f"image-{artwork_id}",
        is_public_domain=True,
        thumbnail=Thumbnail(width=2000, height=1500),
    )


class _StubClient:
    """Stands in for AicClient. Records whether the network tier was reached at all."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def random_displayable(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _service(database: Database, *, client=None, fallback=None, seed: int = 1) -> SelectionService:
    return SelectionService(
        index=ArtworkIndexRepository(database),
        history=HistoryRepository(database),
        preferences=PreferencesRepository(database),
        fallback=fallback if fallback is not None else FallbackSet(),
        client=client,
        rng=random.Random(seed),
    )


class TestTierOrder:
    @pytest.mark.asyncio
    async def test_prefers_the_index_and_does_not_touch_the_network(self, database: Database):
        ArtworkIndexRepository(database).upsert_many_sync([_artwork(1)])
        PreferencesRepository(database).set_sync(IIIF_BASE_KEY, IIIF)
        client = _StubClient(result=(_artwork(99), IIIF))

        selection = await _service(database, client=client).next_artwork()

        assert selection is not None
        assert selection.source == "index"
        assert selection.artwork.id == 1
        assert client.calls == 0

    @pytest.mark.asyncio
    async def test_falls_back_to_aic_when_the_index_is_empty(self, database: Database):
        client = _StubClient(result=(_artwork(42), IIIF))

        selection = await _service(database, client=client).next_artwork()

        assert selection is not None
        assert selection.source == "aic"
        assert selection.artwork.id == 42

    @pytest.mark.asyncio
    async def test_remembers_the_iiif_base_aic_reported(self, database: Database):
        # CLAUDE.md forbids hardcoding it, so it has to be learned and kept.
        client = _StubClient(result=(_artwork(42), IIIF))
        await _service(database, client=client).next_artwork()

        assert PreferencesRepository(database).get_sync(IIIF_BASE_KEY) == IIIF

    @pytest.mark.asyncio
    async def test_falls_back_to_the_bundled_set_when_aic_fails(self, database: Database):
        from app.providers.aic.client import AicUnavailableError

        client = _StubClient(error=AicUnavailableError("down"))
        fallback = FallbackSet(artworks=(_artwork(7),), iiif_base=IIIF)

        selection = await _service(database, client=client, fallback=fallback).next_artwork()

        assert selection is not None
        assert selection.source == "fallback"
        assert selection.artwork.id == 7

    @pytest.mark.asyncio
    async def test_returns_nothing_when_every_tier_is_empty(self, database: Database):
        client = _StubClient(result=None)
        assert await _service(database, client=client).next_artwork() is None

    @pytest.mark.asyncio
    async def test_index_rows_are_unusable_without_a_known_iiif_base(self, database: Database):
        # Rows but no base: we cannot build an image URL and will not invent one, so the
        # next tier gets its turn.
        ArtworkIndexRepository(database).upsert_many_sync([_artwork(1)])
        client = _StubClient(result=(_artwork(42), IIIF))

        selection = await _service(database, client=client).next_artwork()

        assert selection is not None
        assert selection.source == "aic"


class TestHistory:
    @pytest.mark.asyncio
    async def test_records_what_it_showed(self, database: Database):
        ArtworkIndexRepository(database).upsert_many_sync([_artwork(1)])
        PreferencesRepository(database).set_sync(IIIF_BASE_KEY, IIIF)

        await _service(database).next_artwork()

        assert HistoryRepository(database).recent_sync() == [1]

    @pytest.mark.asyncio
    async def test_avoids_repeating_a_just_shown_artwork(self, database: Database):
        ArtworkIndexRepository(database).upsert_many_sync([_artwork(i) for i in (1, 2)])
        PreferencesRepository(database).set_sync(IIIF_BASE_KEY, IIIF)
        service = _service(database)

        first = await service.next_artwork()
        assert first is not None

        # Soft penalty, so this is a tendency rather than a guarantee — assert over runs.
        seconds = []
        for _ in range(30):
            HistoryRepository(database).push_sync(first.artwork.id)
            picked = await service.next_artwork()
            assert picked is not None
            seconds.append(picked.artwork.id)

        other = 2 if first.artwork.id == 1 else 1
        assert seconds.count(other) > seconds.count(first.artwork.id)


class TestFallbackSet:
    def test_a_missing_file_is_not_fatal(self, tmp_path):
        loaded = FallbackSet.load(tmp_path / "absent.json")
        assert loaded.artworks == ()
        assert loaded.random(random.Random()) is None

    def test_a_corrupt_file_is_not_fatal(self, tmp_path):
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert FallbackSet.load(broken).artworks == ()

    def test_the_bundled_set_is_present_and_all_public_domain(self):
        # The shipped file itself, not a fixture: this is the offline story.
        bundled = FallbackSet.load()
        assert len(bundled.artworks) >= 20
        assert bundled.iiif_base
        assert all(a.is_displayable for a in bundled.artworks)


class TestCuratedIsNotAFilter:
    @pytest.mark.asyncio
    async def test_curated_falls_back_to_unranked_when_nothing_is_scored(self, database: Database):
        # Curated is a preference about ordering, not an exclusion. A blank screen with a
        # puzzling message is worse than an unranked artwork.
        from app.services.selection import SelectionQuery

        ArtworkIndexRepository(database).upsert_many_sync([_artwork(1)])
        PreferencesRepository(database).set_sync(IIIF_BASE_KEY, IIIF)

        selection = await _service(database).next_artwork(SelectionQuery(curated=True))

        assert selection is not None
        assert selection.artwork.id == 1

    @pytest.mark.asyncio
    async def test_curated_with_an_empty_index_still_reaches_aic(self, database: Database):
        from app.services.selection import SelectionQuery

        client = _StubClient(result=(_artwork(42), IIIF))
        selection = await _service(database, client=client).next_artwork(
            SelectionQuery(curated=True)
        )

        assert selection is not None
        assert selection.source == "aic"

    @pytest.mark.asyncio
    async def test_a_type_filter_never_falls_through_to_aic(self, database: Database):
        from app.services.selection import SelectionQuery

        client = _StubClient(result=(_artwork(42), IIIF))
        selection = await _service(database, client=client).next_artwork(
            SelectionQuery(facets=("type.painting",))
        )

        assert selection is None
        assert client.calls == 0
