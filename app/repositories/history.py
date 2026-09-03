"""What has been shown recently. Small, append-only, and trimmed."""

import asyncio
from datetime import UTC, datetime

from app.domain.selection import HISTORY_WINDOW
from app.repositories.database import Database


class HistoryRepository:
    """The last ~50 artwork ids, most recent first.

    Trimmed on write rather than swept later: the table exists only to answer "have we
    just shown this?", and an unbounded log of an app that runs for hours is a slow leak.
    """

    def __init__(self, database: Database, window: int = HISTORY_WINDOW) -> None:
        self._db = database
        self._window = window

    def push_sync(self, artwork_id: int) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.connect() as connection:
            connection.execute(
                "INSERT INTO history (artwork_id, shown_at) VALUES (?, ?)", (artwork_id, now)
            )
            connection.execute(
                "DELETE FROM history WHERE rowid NOT IN ("
                "  SELECT rowid FROM history ORDER BY rowid DESC LIMIT ?)",
                (self._window,),
            )

    async def push(self, artwork_id: int) -> None:
        await asyncio.to_thread(self.push_sync, artwork_id)

    def recent_sync(self, limit: int | None = None) -> list[int]:
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT artwork_id FROM history ORDER BY rowid DESC LIMIT ?",
                (limit or self._window,),
            ).fetchall()
        return [int(row["artwork_id"]) for row in rows]

    async def recent(self, limit: int | None = None) -> list[int]:
        return await asyncio.to_thread(self.recent_sync, limit)
