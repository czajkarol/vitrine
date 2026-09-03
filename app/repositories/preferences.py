"""User preferences: a key/value table, deliberately.

The settings panel (M4) grows and changes shape; a column per preference would mean a
migration every time someone adds a toggle. Values are stored as text and interpreted by
the caller, because SQLite would not enforce the types anyway.
"""

import asyncio

from app.repositories.database import Database


class PreferencesRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def get_sync(self, key: str, default: str | None = None) -> str | None:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    async def get(self, key: str, default: str | None = None) -> str | None:
        return await asyncio.to_thread(self.get_sync, key, default)

    def set_sync(self, key: str, value: str) -> None:
        with self._db.connect() as connection:
            connection.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    async def set(self, key: str, value: str) -> None:
        await asyncio.to_thread(self.set_sync, key, value)

    def all_sync(self) -> dict[str, str]:
        with self._db.connect() as connection:
            rows = connection.execute("SELECT key, value FROM preferences").fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def all(self) -> dict[str, str]:
        return await asyncio.to_thread(self.all_sync)
