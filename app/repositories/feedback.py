"""Likes and hides. The only module holding `artwork_feedback`'s SQL.

Small and deliberately dumb: a state per artwork, and two questions the selection path
asks on every rotation — what is hidden, and what has been liked. See migration 009 for
why there is no foreign key, and ADR-0010 for why this is the only signal we collect.
"""

import asyncio
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.repositories.database import Database

FeedbackKind = Literal["like", "hide"]


@dataclass(frozen=True)
class Feedback:
    """One judgement, and enough of the artwork to show it again.

    The snapshot is not denormalisation for speed. It is what lets a favourite outlive the
    index: the artwork may have been served from AIC or from the bundled set and never
    have been indexed at all, and AIC may since have unpublished it.
    """

    artwork_id: int
    kind: FeedbackKind
    title: str | None
    artist: str | None
    image_id: str | None
    created_at: str


def _to_feedback(row: sqlite3.Row) -> Feedback:
    return Feedback(
        artwork_id=row["artwork_id"],
        kind=row["kind"],
        title=row["title"],
        artist=row["artist"],
        image_id=row["image_id"],
        created_at=row["created_at"],
    )


class FeedbackRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def set_sync(
        self,
        artwork_id: int,
        kind: FeedbackKind,
        *,
        title: str | None = None,
        artist: str | None = None,
        image_id: str | None = None,
    ) -> Feedback:
        """Record a like or a hide, replacing whatever was there.

        One row per artwork: liking something previously hidden is a change of mind, not a
        second opinion to be reconciled later.
        """
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.connect() as connection:
            connection.execute(
                "INSERT INTO artwork_feedback"
                " (artwork_id, kind, title, artist, image_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(artwork_id) DO UPDATE SET"
                "   kind = excluded.kind,"
                "   title = COALESCE(excluded.title, artwork_feedback.title),"
                "   artist = COALESCE(excluded.artist, artwork_feedback.artist),"
                "   image_id = COALESCE(excluded.image_id, artwork_feedback.image_id),"
                "   created_at = excluded.created_at",
                (artwork_id, kind, title, artist, image_id, now),
            )
            row = connection.execute(
                "SELECT * FROM artwork_feedback WHERE artwork_id = ?", (artwork_id,)
            ).fetchone()
        return _to_feedback(row)

    async def set(
        self,
        artwork_id: int,
        kind: FeedbackKind,
        *,
        title: str | None = None,
        artist: str | None = None,
        image_id: str | None = None,
    ) -> Feedback:
        return await asyncio.to_thread(
            self.set_sync, artwork_id, kind, title=title, artist=artist, image_id=image_id
        )

    def clear_sync(self, artwork_id: int) -> bool:
        """Un-like or un-hide. Returns whether there was anything to forget."""
        with self._db.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM artwork_feedback WHERE artwork_id = ?", (artwork_id,)
            )
        return cursor.rowcount > 0

    async def clear(self, artwork_id: int) -> bool:
        return await asyncio.to_thread(self.clear_sync, artwork_id)

    def get_sync(self, artwork_id: int) -> Feedback | None:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artwork_feedback WHERE artwork_id = ?", (artwork_id,)
            ).fetchone()
        return _to_feedback(row) if row else None

    async def get(self, artwork_id: int) -> Feedback | None:
        return await asyncio.to_thread(self.get_sync, artwork_id)

    def all_sync(self, kind: FeedbackKind) -> list[Feedback]:
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM artwork_feedback WHERE kind = ? ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
        return [_to_feedback(row) for row in rows]

    async def all(self, kind: FeedbackKind) -> list[Feedback]:
        return await asyncio.to_thread(self.all_sync, kind)

    def ids_sync(self, kind: FeedbackKind) -> list[int]:
        """Just the ids. Asked on every rotation for the hidden set, so it does not carry
        the snapshot columns it has no use for."""
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT artwork_id FROM artwork_feedback WHERE kind = ?", (kind,)
            ).fetchall()
        return [int(row["artwork_id"]) for row in rows]

    async def ids(self, kind: FeedbackKind) -> list[int]:
        return await asyncio.to_thread(self.ids_sync, kind)

    def facets_of_liked_sync(self) -> dict[int, tuple[str, ...]]:
        """The canonical facets of every liked artwork, for the affinity profile.

        A join rather than a query per artwork: this runs whenever the profile is rebuilt,
        which is after every like. Liked artworks that were never indexed contribute
        nothing here and are simply absent — an artwork we know nothing about cannot say
        what you have a taste for.
        """
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT f.artwork_id, af.facet FROM artwork_feedback f"
                " JOIN artwork_facets af ON af.artwork_id = f.artwork_id"
                " WHERE f.kind = 'like'"
            ).fetchall()
        collected: dict[int, list[str]] = {}
        for row in rows:
            collected.setdefault(row["artwork_id"], []).append(row["facet"])
        return {key: tuple(values) for key, values in collected.items()}

    async def facets_of_liked(self) -> dict[int, tuple[str, ...]]:
        return await asyncio.to_thread(self.facets_of_liked_sync)

    def counts_sync(self) -> dict[str, int]:
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT kind, COUNT(*) AS n FROM artwork_feedback GROUP BY kind"
            ).fetchall()
        counts = {"like": 0, "hide": 0}
        counts.update({row["kind"]: int(row["n"]) for row in rows})
        return counts

    async def counts(self) -> dict[str, int]:
        return await asyncio.to_thread(self.counts_sync)


def hidden_clause(hidden: Sequence[int]) -> tuple[str, list[object]]:
    """A WHERE fragment excluding hidden artworks, for the index repository to AND in.

    Here rather than there because "hidden" is this table's idea, and the index repository
    should not need to know that a second table has an opinion about its rows.
    """
    if not hidden:
        return "", []
    placeholders = ",".join("?" for _ in hidden)
    return f"id NOT IN ({placeholders})", list(hidden)
