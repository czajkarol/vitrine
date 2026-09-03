"""Reads and writes for `artwork_index`. The only module holding its SQL."""

import asyncio
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.artwork import Artwork, Color, Thumbnail
from app.repositories.database import Database

_COLUMNS = """
    id, image_id, title, artist, date_display, medium_display, credit_line,
    place_of_origin, department_title, classification, main_reference_number,
    description, width, height, is_boosted, has_alt_text, alt_text, lqip,
    color_h, color_s, color_l, score, indexed_at
"""

_UPSERT = f"""
INSERT INTO artwork_index ({_COLUMNS})
VALUES (:id, :image_id, :title, :artist, :date_display, :medium_display, :credit_line,
        :place_of_origin, :department_title, :classification, :main_reference_number,
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
    classification = excluded.classification,
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
        "title": artwork.title,
        "artist": artwork.artist_title,
        "date_display": artwork.date_display,
        "medium_display": artwork.medium_display,
        "credit_line": artwork.credit_line,
        "place_of_origin": artwork.place_of_origin,
        "department_title": artwork.department_title,
        "classification": artwork.artwork_type_title,
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


def _to_artwork(row: sqlite3.Row) -> Artwork:
    """Rebuild the domain model. The index stores a subset, so this is lossy by design."""
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
    return Artwork(
        id=row["id"],
        title=row["title"],
        artist_title=row["artist"],
        date_display=row["date_display"],
        medium_display=row["medium_display"],
        credit_line=row["credit_line"],
        place_of_origin=row["place_of_origin"],
        department_title=row["department_title"],
        artwork_type_title=row["classification"],
        main_reference_number=row["main_reference_number"],
        description=row["description"],
        image_id=row["image_id"],
        # Only public-domain works are ever written here, so reading one back is proof.
        is_public_domain=True,
        is_boosted=bool(row["is_boosted"]),
        thumbnail=thumbnail,
        color=colour,
    )


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
        return len(rows)

    async def upsert_many(self, artworks: Sequence[Artwork]) -> int:
        return await asyncio.to_thread(self.upsert_many_sync, artworks)

    # --- reads --------------------------------------------------------------------

    def count_sync(self) -> int:
        with self._db.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM artwork_index").fetchone()
        return int(row["n"])

    async def count(self) -> int:
        return await asyncio.to_thread(self.count_sync)

    def sample_sync(self, limit: int) -> list[Artwork]:
        """A random pool of candidates.

        Sampling here and applying the history penalty in `domain/selection.py` keeps the
        rule pure and testable; doing it in SQL would bury it in a query.
        """
        with self._db.connect() as connection:
            rows = connection.execute(
                f"SELECT {_COLUMNS} FROM artwork_index ORDER BY RANDOM() LIMIT ?",
                (limit,),
            ).fetchall()
        return [_to_artwork(row) for row in rows]

    async def sample(self, limit: int) -> list[Artwork]:
        return await asyncio.to_thread(self.sample_sync, limit)

    def get_sync(self, artwork_id: int) -> Artwork | None:
        with self._db.connect() as connection:
            row = connection.execute(
                f"SELECT {_COLUMNS} FROM artwork_index WHERE id = ?",
                (artwork_id,),
            ).fetchone()
        return _to_artwork(row) if row else None

    async def get(self, artwork_id: int) -> Artwork | None:
        return await asyncio.to_thread(self.get_sync, artwork_id)
