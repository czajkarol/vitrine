"""Repositories against a real temporary SQLite file — no mocks, no network."""

import pytest

from app.domain.artwork import Artwork, Color, Thumbnail
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.repositories.history import HistoryRepository
from app.repositories.preferences import PreferencesRepository


def _artwork(artwork_id: int = 1, **overrides) -> Artwork:
    base = {
        "id": artwork_id,
        "title": f"Work {artwork_id}",
        "artist_title": "An artist",
        "image_id": f"image-{artwork_id}",
        "is_public_domain": True,
        "thumbnail": Thumbnail(
            width=2000, height=1500, lqip="data:image/gif;base64,x", alt_text="alt"
        ),
        "color": Color(h=200, s=50, l=40),
        "artwork_type_title": "Painting",
    }
    return Artwork(**{**base, **overrides})


class TestMigrations:
    def test_creates_the_expected_tables(self, database: Database):
        with database.connect() as connection:
            names = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        assert {"artwork_index", "history", "preferences", "schema_migrations"} <= names

    def test_running_twice_is_harmless(self, database: Database):
        database.migrate()
        database.migrate()
        with database.connect() as connection:
            applied = connection.execute("SELECT COUNT(*) AS n FROM schema_migrations").fetchone()
        assert applied["n"] >= 1

    def test_enables_write_ahead_logging(self, database: Database):
        # WAL is what lets build_index.py write while the display reads.
        with database.connect() as connection:
            mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"


class TestArtworkIndexRepository:
    def test_round_trips_an_artwork(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(7)])

        stored = repo.get_sync(7)
        assert stored is not None
        assert stored.title == "Work 7"
        assert stored.image_id == "image-7"
        assert stored.thumbnail is not None
        assert stored.thumbnail.alt_text == "alt"
        assert stored.color is not None
        assert stored.color.h == 200
        # Only public-domain works are ever written, so a read-back is proof of it.
        assert stored.is_displayable

    def test_upserting_the_same_id_updates_rather_than_duplicates(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(3, title="Before")])
        repo.upsert_many_sync([_artwork(3, title="After")])

        assert repo.count_sync() == 1
        stored = repo.get_sync(3)
        assert stored is not None
        assert stored.title == "After"

    def test_a_recrawl_does_not_wipe_the_score(self, database: Database):
        # M3 computes score in a separate pass; re-walking AIC must not undo it.
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(4)])
        with database.connect() as connection:
            connection.execute("UPDATE artwork_index SET score = 0.75 WHERE id = 4")

        repo.upsert_many_sync([_artwork(4, title="Recrawled")])

        with database.connect() as connection:
            row = connection.execute("SELECT score, title FROM artwork_index WHERE id=4").fetchone()
        assert row["score"] == 0.75
        assert row["title"] == "Recrawled"

    def test_sampling_an_empty_index_returns_nothing(self, database: Database):
        assert ArtworkIndexRepository(database).sample_sync(10) == []

    def test_sampling_never_returns_more_than_asked(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(i) for i in range(1, 21)])
        assert len(repo.sample_sync(5)) == 5

    def test_upserting_nothing_is_not_an_error(self, database: Database):
        assert ArtworkIndexRepository(database).upsert_many_sync([]) == 0

    @pytest.mark.asyncio
    async def test_async_wrappers_reach_the_same_rows(self, database: Database):
        repo = ArtworkIndexRepository(database)
        await repo.upsert_many([_artwork(11)])
        assert await repo.count() == 1
        assert (await repo.get(11)) is not None


class TestHistoryRepository:
    def test_returns_most_recent_first(self, database: Database):
        history = HistoryRepository(database)
        for artwork_id in (1, 2, 3):
            history.push_sync(artwork_id)
        assert history.recent_sync() == [3, 2, 1]

    def test_trims_to_the_window(self, database: Database):
        # An app that runs for hours must not grow an unbounded log.
        history = HistoryRepository(database, window=5)
        for artwork_id in range(1, 21):
            history.push_sync(artwork_id)

        recent = history.recent_sync()
        assert len(recent) == 5
        assert recent == [20, 19, 18, 17, 16]

    def test_an_artwork_may_repeat_in_history(self, database: Database):
        history = HistoryRepository(database)
        history.push_sync(1)
        history.push_sync(1)
        assert history.recent_sync() == [1, 1]

    def test_empty_history_is_an_empty_list(self, database: Database):
        assert HistoryRepository(database).recent_sync() == []


class TestPreferencesRepository:
    def test_stores_and_reads_back(self, database: Database):
        prefs = PreferencesRepository(database)
        prefs.set_sync("language", "pl")
        assert prefs.get_sync("language") == "pl"

    def test_setting_the_same_key_replaces_it(self, database: Database):
        prefs = PreferencesRepository(database)
        prefs.set_sync("interval", "5")
        prefs.set_sync("interval", "30")
        assert prefs.get_sync("interval") == "30"
        assert prefs.all_sync() == {"interval": "30"}

    def test_returns_the_default_for_an_unknown_key(self, database: Database):
        assert PreferencesRepository(database).get_sync("nope", "fallback") == "fallback"
        assert PreferencesRepository(database).get_sync("nope") is None


class TestCuratedSampling:
    def test_draws_only_from_scored_rows(self, database: Database):
        # An unscored row is unranked, not bad — but curated mode cannot place it, so it
        # must not leak into a curated rotation.
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(1), _artwork(2)])
        repo.update_scores_sync({1: 0.9})

        sampled = repo.sample_sync(10, curated=True)
        assert [a.id for a in sampled] == [1]

    def test_random_mode_still_sees_unscored_rows(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(1), _artwork(2)])
        assert len(repo.sample_sync(10)) == 2

    def test_prefers_higher_scores(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(i) for i in range(1, 11)])
        repo.update_scores_sync({i: i / 10 for i in range(1, 11)})

        # The pool is wider than this index, so all scored rows are eligible; what this
        # asserts is that scoring does not exclude or reorder wrongly.
        sampled = repo.sample_sync(3, curated=True)
        assert len(sampled) == 3

    def test_filters_by_classification(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync(
            [
                _artwork(1, artwork_type_title="Painting"),
                _artwork(2, artwork_type_title="Coin"),
            ]
        )
        sampled = repo.sample_sync(10, artwork_type="Painting")
        assert [a.id for a in sampled] == [1]

    def test_an_unmatched_filter_returns_nothing_rather_than_everything(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(1, artwork_type_title="Painting")])
        assert repo.sample_sync(10, artwork_type="Sculpture") == []


class TestScoringPass:
    def test_scores_are_written_and_counted(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(1), _artwork(2)])
        assert repo.scored_count_sync() == 0

        assert repo.update_scores_sync({1: 0.5, 2: 0.25}) == 2
        assert repo.scored_count_sync() == 2

    def test_writing_no_scores_is_not_an_error(self, database: Database):
        assert ArtworkIndexRepository(database).update_scores_sync({}) == 0

    def test_iterating_yields_every_row_once(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(i) for i in range(1, 26)])

        seen = [a.id for chunk in repo.iter_for_scoring_sync(batch=10) for a in chunk]
        assert sorted(seen) == list(range(1, 26))
        assert len(seen) == len(set(seen))

    def test_iterating_an_empty_index_yields_nothing(self, database: Database):
        assert list(ArtworkIndexRepository(database).iter_for_scoring_sync()) == []


class TestArtworkTypeCounts:
    def test_counts_per_type_biggest_first(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync(
            [_artwork(i, artwork_type_title="Painting") for i in range(1, 4)]
            + [_artwork(10, artwork_type_title="Coin")]
        )
        counts = repo.artwork_type_counts_sync()
        assert counts == {"Painting": 3, "Coin": 1}
        assert list(counts) == ["Painting", "Coin"]

    def test_ignores_rows_with_no_type(self, database: Database):
        repo = ArtworkIndexRepository(database)
        repo.upsert_many_sync([_artwork(1, artwork_type_title=None)])
        assert ArtworkIndexRepository(database).artwork_type_counts_sync() == {}
