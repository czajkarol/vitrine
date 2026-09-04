"""Exporting the corpus and merging one back, against real temporary SQLite files.

The tests that matter here are about what is *not* copied. An export is a file the owner
uploads somewhere public, and the database it is cut from holds an API key, so "only the
corpus tables" is a safety property rather than a tidiness one — see ADR-0011.
"""

import sqlite3
from pathlib import Path

import pytest

from app.domain.artwork import Artwork, Color, Thumbnail
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.corpus import (
    CORPUS_TABLES,
    EXPORTED_TABLES,
    CorpusError,
    describe_export,
    export_corpus,
    merge_corpus,
)
from app.repositories.credentials import SqliteCredentialStore
from app.repositories.database import Database
from app.repositories.feedback import FeedbackRepository
from app.repositories.preferences import PreferencesRepository

SECRET = "sk-ant-notarealkey-0000000000000000000000"


def _artwork(artwork_id: int, **overrides) -> Artwork:
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
        "style_titles": ["Impressionism"],
        "subject_titles": ["landscapes"],
    }
    return Artwork(**{**base, **overrides})


@pytest.fixture
async def populated(database: Database) -> Database:
    """A database that looks like a real one: corpus, plus every private table filled."""
    index = ArtworkIndexRepository(database)
    await index.upsert_many([_artwork(i) for i in range(1, 6)])
    # Scored, because a real index is. An export that dropped the score would arrive
    # looking complete and leave curated mode serving nothing.
    await index.update_scores({i: 0.5 + i / 100 for i in range(1, 6)})
    await PreferencesRepository(database).set("language", "pl")
    await SqliteCredentialStore(database).set("anthropic", SECRET)
    await FeedbackRepository(database).set(3, "like", title="Work 3", artist="An artist")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO history (artwork_id, shown_at) VALUES (1, '2026-09-04T00:00:00Z')"
        )
    return database


class TestExport:
    async def test_contains_only_the_allow_listed_tables(self, populated: Database, tmp_path):
        result = export_corpus(populated, tmp_path / "export.sqlite")

        with sqlite3.connect(result.path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                )
            }
        assert tables == set(EXPORTED_TABLES)

    async def test_carries_no_secret(self, populated: Database, tmp_path):
        """The blunt version of the test above, and the one that would survive a rename.

        A key sits in `credentials` in the same file as the index. If a future table ever
        carries one somewhere else, the allow-list test still passes and this one does not.
        """
        result = export_corpus(populated, tmp_path / "export.sqlite")
        assert SECRET.encode() not in result.path.read_bytes()

    async def test_carries_no_user_state(self, populated: Database, tmp_path):
        result = export_corpus(populated, tmp_path / "export.sqlite")
        summary = describe_export(result.path)
        assert summary.artworks == 5
        # The preference value, the favourite and the history row are all absent because
        # the tables holding them are.
        assert b"language" not in result.path.read_bytes()

    async def test_copies_the_corpus_intact(self, populated: Database, tmp_path):
        result = export_corpus(populated, tmp_path / "export.sqlite")
        assert result.rows["artwork_index"] == 5
        assert result.rows["artwork_terms"] == 10  # one style and one subject each
        assert result.rows["artwork_facets"] >= 5
        assert result.size_bytes > 0

    async def test_keeps_the_indexes(self, populated: Database, tmp_path):
        """Without these a fetched corpus is correct and slow: every settings-panel open
        becomes a full scan of `artwork_facets`."""
        result = export_corpus(populated, tmp_path / "export.sqlite")
        with sqlite3.connect(result.path) as connection:
            indexes = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
            }
        assert "idx_artwork_facets_facet" in indexes
        assert "idx_artwork_index_score" in indexes

    async def test_leaves_no_partial_file_behind(self, populated: Database, tmp_path):
        destination = tmp_path / "export.sqlite"
        export_corpus(populated, destination)
        assert not destination.with_name(destination.name + ".partial").exists()

    def test_refuses_a_database_that_does_not_exist(self, tmp_path):
        with pytest.raises(CorpusError, match="no database"):
            export_corpus(Database(tmp_path / "absent.db"), tmp_path / "export.sqlite")


class TestDescribeExport:
    def test_rejects_a_file_that_is_not_sqlite(self, tmp_path):
        """The ordinary way a download goes wrong: an HTML error page under a .sqlite name."""
        impostor = tmp_path / "export.sqlite"
        impostor.write_text("<html><body>404 Not Found</body></html>", encoding="utf-8")
        with pytest.raises(CorpusError, match="not a readable SQLite database"):
            describe_export(impostor)

    def test_rejects_an_empty_file(self, tmp_path):
        empty = tmp_path / "export.sqlite"
        empty.touch()
        with pytest.raises(CorpusError, match="empty"):
            describe_export(empty)

    async def test_rejects_a_database_that_is_not_an_export(self, populated: Database):
        """A whole `vitrine.db` handed to `--file` by mistake. It has the corpus tables and
        several more, and merging from it would be merging from a file with a key in it."""
        with pytest.raises(CorpusError, match="not a vitrine index export"):
            describe_export(populated.path)

    def test_rejects_a_missing_file(self, tmp_path):
        with pytest.raises(CorpusError, match="no such file"):
            describe_export(tmp_path / "absent.sqlite")


class TestMerge:
    @pytest.fixture
    async def export_file(self, populated: Database, tmp_path) -> Path:
        return export_corpus(populated, tmp_path / "export.sqlite").path

    async def test_fills_an_empty_database(self, export_file: Path, tmp_path):
        target = Database(tmp_path / "fresh.db")
        result = merge_corpus(target, export_file)

        assert result.artworks_before == 0
        assert result.artworks_after == 5
        assert result.added == 5
        assert await ArtworkIndexRepository(target).count() == 5

    async def test_leaves_preferences_favourites_and_credentials_alone(
        self, export_file: Path, tmp_path
    ):
        """The whole promise of `fetch_index.py`: a downloaded corpus is not a factory reset."""
        target = Database(tmp_path / "mine.db")
        target.migrate()
        await PreferencesRepository(target).set("language", "pl")
        await SqliteCredentialStore(target).set("anthropic", SECRET)
        await FeedbackRepository(target).set(99, "like", title="Something I liked")

        merge_corpus(target, export_file)

        assert await PreferencesRepository(target).get("language") == "pl"
        assert await SqliteCredentialStore(target).get("anthropic") == SECRET
        assert [f.artwork_id for f in await FeedbackRepository(target).all("like")] == [99]

    async def test_refreshes_rows_it_already_has(self, export_file: Path, tmp_path):
        target = Database(tmp_path / "stale.db")
        target.migrate()
        index = ArtworkIndexRepository(target)
        await index.upsert_many([_artwork(1, title="An older title")])

        result = merge_corpus(target, export_file)

        assert result.artworks_before == 1
        assert result.added == 4
        refreshed = await index.get(1)
        assert refreshed is not None
        assert refreshed.title == "Work 1"

    async def test_keeps_the_terms_of_a_refreshed_artwork(self, export_file: Path, tmp_path):
        """`artwork_terms` and `artwork_facets` cascade on delete, and `INSERT OR REPLACE`
        on a parent is a delete. Merge the children first and the parent wipes them, which
        is why `CORPUS_TABLES` is ordered rather than alphabetical."""
        target = Database(tmp_path / "stale.db")
        target.migrate()
        await ArtworkIndexRepository(target).upsert_many([_artwork(1, title="An older title")])

        merge_corpus(target, export_file)

        with target.connect() as connection:
            terms = connection.execute(
                "SELECT COUNT(*) AS n FROM artwork_terms WHERE artwork_id = 1"
            ).fetchone()["n"]
            facets = connection.execute(
                "SELECT COUNT(*) AS n FROM artwork_facets WHERE artwork_id = 1"
            ).fetchone()["n"]
        assert terms == 2
        assert facets > 0

    async def test_is_idempotent(self, export_file: Path, tmp_path):
        target = Database(tmp_path / "fresh.db")
        merge_corpus(target, export_file)
        again = merge_corpus(target, export_file)
        assert again.added == 0
        assert again.artworks_after == 5

    async def test_refuses_an_export_from_a_newer_schema(self, export_file: Path, tmp_path):
        """A published export outliving the checkout that reads it. Writing its rows into a
        schema that has not caught up is how a column silently goes missing."""
        with Database(export_file).connect() as connection:
            connection.execute(
                "INSERT INTO schema_migrations (name) VALUES ('099_from_the_future.sql')"
            )

        with pytest.raises(CorpusError, match="does not have"):
            merge_corpus(Database(tmp_path / "fresh.db"), export_file)

    async def test_a_merged_corpus_is_immediately_usable(self, export_file: Path, tmp_path):
        """Not a tautology: sampling reads `artwork_facets` and the score index, so this is
        what proves the derived tables came across and not just the rows."""
        target = Database(tmp_path / "fresh.db")
        merge_corpus(target, export_file)
        index = ArtworkIndexRepository(target)
        # Curated sampling requires a non-null score, so this is also the assertion that
        # the export carries one: a fetched index must not need a local scoring pass
        # before the mode the app defaults to has anything to serve.
        pool = await index.sample(limit=5, curated=True)
        assert len(pool) == 5
        # Facet filtering reads artwork_facets, which is derived and easy to leave behind.
        filtered = await index.sample(limit=5, facets=[["type.painting"]])
        assert filtered


class TestRoundTrip:
    async def test_export_then_merge_preserves_every_corpus_table(
        self, populated: Database, tmp_path
    ):
        export = export_corpus(populated, tmp_path / "export.sqlite")
        target = Database(tmp_path / "fresh.db")
        merge_corpus(target, export.path)

        with populated.connect() as before, target.connect() as after:
            for table in CORPUS_TABLES:
                original = before.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                copied = after.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
                assert copied == original, table
