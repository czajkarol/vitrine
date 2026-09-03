"""Reads and writes for `artwork_index`. The only module holding its SQL."""

import asyncio
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Final

from app.domain.artwork import Artwork, Color, Thumbnail
from app.repositories.database import Database

# How many of the best-scoring rows curated mode draws from. Wide enough that the
# rotation does not repeat the same twenty masterpieces all evening.
CURATED_POOL: Final[int] = 500

TERM_KINDS: Final[tuple[str, ...]] = ("style", "subject")
"""The two multi-valued vocabularies, stored in `artwork_terms`. Kept as data rather than
as two near-identical code paths: they are queried identically and differ only in which
AIC field they came from."""

_COLUMNS = """
    id, image_id, title, artist, date_display, medium_display, credit_line,
    place_of_origin, department_title, artwork_type, main_reference_number,
    description, width, height, is_boosted, has_alt_text, alt_text, lqip,
    color_h, color_s, color_l, score, indexed_at
"""

_UPSERT = f"""
INSERT INTO artwork_index ({_COLUMNS})
VALUES (:id, :image_id, :title, :artist, :date_display, :medium_display, :credit_line,
        :place_of_origin, :department_title, :artwork_type, :main_reference_number,
        :description, :width, :height, :is_boosted, :has_alt_text, :alt_text, :lqip,
        :color_h, :color_s, :color_l, :score, :indexed_at)
ON CONFLICT(id) DO UPDATE SET
    image_id = excluded.image_id,
    title = excluded.title,
    artist = excluded.artist,
    date_display = excluded.date_display,
    medium_display = excluded.medium_display,
    credit_line = excluded.credit_line,
    place_of_origin = excluded.place_of_origin,
    department_title = excluded.department_title,
    artwork_type = excluded.artwork_type,
    main_reference_number = excluded.main_reference_number,
    description = excluded.description,
    width = excluded.width,
    height = excluded.height,
    is_boosted = excluded.is_boosted,
    has_alt_text = excluded.has_alt_text,
    alt_text = excluded.alt_text,
    lqip = excluded.lqip,
    color_h = excluded.color_h,
    color_s = excluded.color_s,
    color_l = excluded.color_l,
    indexed_at = excluded.indexed_at
"""
# `score` is deliberately absent from the UPDATE list: M3 computes it in a separate pass,
# and a re-crawl must not wipe it.


def _to_row(artwork: Artwork) -> dict[str, object]:
    thumbnail = artwork.thumbnail
    colour = artwork.color
    return {
        "id": artwork.id,
        "image_id": artwork.image_id,
        # The column is NOT NULL and an absent title means the same thing as an empty
        # one to this app, so it is stored as "". AIC does return null here.
        "title": artwork.title or "",
        "artist": artwork.artist_title,
        "date_display": artwork.date_display,
        "medium_display": artwork.medium_display,
        "credit_line": artwork.credit_line,
        "place_of_origin": artwork.place_of_origin,
        "department_title": artwork.department_title,
        "artwork_type": artwork.artwork_type_title,
        "main_reference_number": artwork.main_reference_number,
        "description": artwork.description,
        "width": thumbnail.width if thumbnail else None,
        "height": thumbnail.height if thumbnail else None,
        "is_boosted": int(artwork.is_boosted),
        "has_alt_text": int(bool(thumbnail and thumbnail.alt_text)),
        "alt_text": thumbnail.alt_text if thumbnail else None,
        "lqip": thumbnail.lqip if thumbnail else None,
        "color_h": colour.h if colour else None,
        "color_s": colour.s if colour else None,
        "color_l": colour.l if colour else None,
        "score": None,
        "indexed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _to_artwork(
    row: sqlite3.Row, terms: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] | None = None
) -> Artwork:
    """Rebuild the domain model. The index stores a subset, so this is lossy by design.

    `terms` is the batched style/subject lookup from `_terms_for`, keyed by artwork id.
    Passing None means the caller does not need them and they come back empty — which is
    safe only because writing terms is a separate statement from writing the row, so a
    model read back without them cannot wipe them on the way in again.
    """
    thumbnail = Thumbnail(
        lqip=row["lqip"],
        width=row["width"],
        height=row["height"],
        alt_text=row["alt_text"],
    )
    colour = (
        Color(h=row["color_h"], s=row["color_s"], l=row["color_l"])
        if row["color_h"] is not None
        else None
    )
    styles, subjects = (terms or {}).get(row["id"], ((), ()))
    return Artwork(
        id=row["id"],
        title=row["title"],
        artist_title=row["artist"],
        date_display=row["date_display"],
        medium_display=row["medium_display"],
        credit_line=row["credit_line"],
        place_of_origin=row["place_of_origin"],
        department_title=row["department_title"],
        artwork_type_title=row["artwork_type"],
        main_reference_number=row["main_reference_number"],
        description=row["description"],
        image_id=row["image_id"],
        # Only public-domain works are ever written here, so reading one back is proof.
        is_public_domain=True,
        is_boosted=bool(row["is_boosted"]),
        thumbnail=thumbnail,
        color=colour,
        style_titles=styles,
        subject_titles=subjects,
    )


def _terms_for(
    connection: sqlite3.Connection, artwork_ids: Sequence[int]
) -> dict[int, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Style and subject for a batch of artworks, in one query rather than one each.

    Every read path goes through here, so a sample of two hundred rows costs two queries
    in total instead of two hundred and one.
    """
    if not artwork_ids:
        return {}
    placeholders = ",".join("?" for _ in artwork_ids)
    rows = connection.execute(
        f"SELECT artwork_id, kind, value FROM artwork_terms "
        f"WHERE artwork_id IN ({placeholders}) ORDER BY value",
        list(artwork_ids),
    ).fetchall()

    collected: dict[int, tuple[list[str], list[str]]] = {}
    for row in rows:
        styles, subjects = collected.setdefault(row["artwork_id"], ([], []))
        (styles if row["kind"] == "style" else subjects).append(row["value"])
    return {key: (tuple(styles), tuple(subjects)) for key, (styles, subjects) in collected.items()}


def _to_artworks(connection: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[Artwork]:
    """Rows to domain models, with their terms attached."""
    terms = _terms_for(connection, [row["id"] for row in rows])
    return [_to_artwork(row, terms) for row in rows]


class ArtworkIndexRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    # --- writes -------------------------------------------------------------------

    def upsert_many_sync(self, artworks: Sequence[Artwork]) -> int:
        """Insert or refresh rows. Idempotent — re-running the crawler updates in place."""
        if not artworks:
            return 0
        rows = [_to_row(artwork) for artwork in artworks]
        with self._db.connect() as connection:
            connection.executemany(_UPSERT, rows)
            self._replace_terms(connection, artworks)
        return len(rows)

    @staticmethod
    def _replace_terms(connection: sqlite3.Connection, artworks: Sequence[Artwork]) -> None:
        """Rewrite each artwork's style and subject rows.

        Delete-then-insert rather than an upsert, because a term can be *removed* upstream
        and an upsert would leave the old one behind forever. The whole set for an artwork
        is small — seventeen subjects on the fattest record measured — so replacing it is
        cheaper than working out the difference.
        """
        ids = [(artwork.id,) for artwork in artworks]
        connection.executemany("DELETE FROM artwork_terms WHERE artwork_id = ?", ids)
        connection.executemany(
            "INSERT OR IGNORE INTO artwork_terms (artwork_id, kind, value) VALUES (?, ?, ?)",
            [
                (artwork.id, kind, value)
                for artwork in artworks
                for kind, values in (
                    ("style", artwork.style_titles),
                    ("subject", artwork.subject_titles),
                )
                for value in values
                if value.strip()
            ],
        )

    async def upsert_many(self, artworks: Sequence[Artwork]) -> int:
        return await asyncio.to_thread(self.upsert_many_sync, artworks)

    # --- reads --------------------------------------------------------------------

    def count_sync(self) -> int:
        with self._db.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM artwork_index").fetchone()
        return int(row["n"])

    async def count(self) -> int:
        return await asyncio.to_thread(self.count_sync)

    def sample_sync(
        self,
        limit: int,
        curated: bool = False,
        artwork_type: str | None = None,
        style: str | None = None,
        subject: str | None = None,
    ) -> list[Artwork]:
        """A pool of candidates.

        Sampling here and applying the history penalty in `domain/selection.py` keeps the
        rule pure and testable; doing it in SQL would bury it in a query.

        Curated mode draws from the highest-scoring rows instead of the whole index. Rows
        scored NULL are excluded there rather than sorted to one end, because an unscored
        row is unranked, not bad — it just has not been through a scoring pass yet.

        The three filters combine with AND. Style and subject go through `artwork_terms`,
        so a work needs a matching row there rather than a matching column.
        """
        where: list[str] = []
        params: list[object] = []
        if artwork_type:
            where.append("artwork_type = ?")
            params.append(artwork_type)
        for kind, value in (("style", style), ("subject", subject)):
            if not value:
                continue
            # IN over the (kind, value) index, rather than a correlated EXISTS: this way
            # the term index picks the ids and the primary key does the rest.
            where.append(
                "id IN (SELECT artwork_id FROM artwork_terms WHERE kind = ? AND value = ?)"
            )
            params.extend([kind, value])
        if curated:
            where.append("score IS NOT NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        if curated:
            # Take the best CURATED_POOL rows, then pick randomly inside them, so a
            # curated rotation is varied without ever dropping to the bottom of the index.
            sql = (
                f"SELECT {_COLUMNS} FROM ("
                f"  SELECT {_COLUMNS} FROM artwork_index {clause}"
                f"  ORDER BY score DESC LIMIT ?"
                f") ORDER BY RANDOM() LIMIT ?"
            )
            params.extend([CURATED_POOL, limit])
        else:
            sql = f"SELECT {_COLUMNS} FROM artwork_index {clause} ORDER BY RANDOM() LIMIT ?"
            params.append(limit)

        with self._db.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            return _to_artworks(connection, rows)

    async def sample(
        self,
        limit: int,
        curated: bool = False,
        artwork_type: str | None = None,
        style: str | None = None,
        subject: str | None = None,
    ) -> list[Artwork]:
        return await asyncio.to_thread(
            self.sample_sync, limit, curated, artwork_type, style, subject
        )

    def artwork_type_counts_sync(self) -> dict[str, int]:
        """How many indexed artworks sit behind each artwork type.

        Explore uses this to decide what is worth offering: a filter with four artworks
        behind it is worse than no filter (docs/product-spec.md).
        """
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT artwork_type, COUNT(*) AS n FROM artwork_index "
                "WHERE artwork_type IS NOT NULL GROUP BY artwork_type ORDER BY n DESC"
            ).fetchall()
        return {row["artwork_type"]: int(row["n"]) for row in rows}

    async def artwork_type_counts(self) -> dict[str, int]:
        return await asyncio.to_thread(self.artwork_type_counts_sync)

    def term_counts_sync(self, kind: str, limit: int | None = None) -> dict[str, int]:
        """How many indexed artworks carry each style, or each subject.

        The same question `artwork_type_counts` answers, against the other table. It takes
        a limit because these vocabularies are large where the artwork types are not:
        one listing page of a hundred records carried 152 distinct subjects, so the whole
        index has thousands and a settings panel cannot offer them all.
        """
        if kind not in TERM_KINDS:
            raise ValueError(f"unknown term kind {kind!r}")
        sql = (
            "SELECT value, COUNT(*) AS n FROM artwork_terms WHERE kind = ? "
            "GROUP BY value ORDER BY n DESC, value"
        )
        params: list[object] = [kind]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._db.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return {row["value"]: int(row["n"]) for row in rows}

    async def term_counts(self, kind: str, limit: int | None = None) -> dict[str, int]:
        return await asyncio.to_thread(self.term_counts_sync, kind, limit)

    # --- scoring ------------------------------------------------------------------

    def iter_for_scoring_sync(self, batch: int = 1000) -> Iterator[list[Artwork]]:
        """Every row, in batches, so a scoring pass does not hold the whole index in RAM."""
        offset = 0
        while True:
            with self._db.connect() as connection:
                rows = connection.execute(
                    f"SELECT {_COLUMNS} FROM artwork_index ORDER BY id LIMIT ? OFFSET ?",
                    (batch, offset),
                ).fetchall()
                if not rows:
                    return
                batch_of_artworks = _to_artworks(connection, rows)
            yield batch_of_artworks
            offset += len(rows)

    def update_scores_sync(self, scores: dict[int, float]) -> int:
        """Write computed scores. Separate from the crawl so weights can be retuned
        without walking AIC again."""
        if not scores:
            return 0
        with self._db.connect() as connection:
            connection.executemany(
                "UPDATE artwork_index SET score = ? WHERE id = ?",
                [(value, artwork_id) for artwork_id, value in scores.items()],
            )
        return len(scores)

    async def update_scores(self, scores: dict[int, float]) -> int:
        return await asyncio.to_thread(self.update_scores_sync, scores)

    def scored_count_sync(self) -> int:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM artwork_index WHERE score IS NOT NULL"
            ).fetchone()
        return int(row["n"])

    def get_sync(self, artwork_id: int) -> Artwork | None:
        with self._db.connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM artwork_index WHERE id = ?",
                (artwork_id,),
            ).fetchone()
            return _to_artworks(connection, [row])[0] if row else None

    async def get(self, artwork_id: int) -> Artwork | None:
        return await asyncio.to_thread(self.get_sync, artwork_id)
