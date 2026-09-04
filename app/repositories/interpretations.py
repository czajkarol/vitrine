"""Where interpretations are kept: one real cache, and one that never has anything.

Both implement `InterpretationCache`. The empty one is not a placeholder — it is what makes
the three-tier resolution chain in `docs/ai-system.md` ordinary code that runs and is
tested, so that enabling a shared cache later is a config change and one new class rather
than a redesign. See ADR-0004.

Every failure here degrades to a miss. A cache that can take the display down is worse
than no cache: the museum's own facts are still on screen, and the worst a miss costs is
one more provider call.
"""

import asyncio
import logging
import sqlite3

from pydantic import ValidationError

from app.domain.interpretation import CachedValue, CacheKey, Interpretation, VisualDescription
from app.repositories.database import Database

logger = logging.getLogger(__name__)

# Which model a row validates into, decided by the key's `kind`. One table holds both
# because they are the same thing operationally — generated text, keyed by artwork,
# language, provider, model and prompt version — and two tables would have been two copies
# of this file. See `domain/interpretation.py`.
_MODELS: dict[str, type[CachedValue]] = {
    "interpretation": Interpretation,
    "visual": VisualDescription,
}


class SqliteInterpretationCache:
    """The local cache. First tier, and the only one that stores anything."""

    name = "local"

    def __init__(self, database: Database) -> None:
        self._db = database

    def get_sync(self, key: CacheKey) -> CachedValue | None:
        try:
            with self._db.connect() as connection:
                row = connection.execute(
                    "SELECT payload_json FROM interpretations WHERE cache_key = ?",
                    (key.as_string(),),
                ).fetchone()
        except sqlite3.Error as exc:
            logger.warning("Interpretation cache read failed for %s: %s", key.as_string(), exc)
            return None

        if row is None:
            return None

        try:
            return _MODELS[key.kind].model_validate_json(row["payload_json"])
        except ValidationError as exc:
            # Written by an older shape, or corrupted. Validating on the way out is the
            # point: a row that no longer fits must not reach the display unchecked.
            logger.warning("Discarding unusable cached interpretation %s: %s", key.as_string(), exc)
            return None

    async def get(self, key: CacheKey) -> CachedValue | None:
        return await asyncio.to_thread(self.get_sync, key)

    def put_sync(self, key: CacheKey, value: CachedValue) -> None:
        try:
            with self._db.connect() as connection:
                connection.execute(
                    "INSERT INTO interpretations ("
                    " cache_key, artwork_id, language, provider, model, prompt_version,"
                    " kind, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(cache_key) DO UPDATE SET"
                    " payload_json = excluded.payload_json,"
                    " created_at = CURRENT_TIMESTAMP",
                    (
                        key.as_string(),
                        key.artwork_id,
                        key.language,
                        key.provider,
                        key.model,
                        key.prompt_version,
                        key.kind,
                        value.model_dump_json(),
                    ),
                )
        except sqlite3.Error as exc:
            # The interpretation is already on its way to the screen. Failing to keep a
            # copy of it is not worth interrupting that.
            logger.warning("Interpretation cache write failed for %s: %s", key.as_string(), exc)

    async def put(self, key: CacheKey, value: CachedValue) -> None:
        await asyncio.to_thread(self.put_sync, key, value)

    def count_sync(self) -> int:
        with self._db.connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) AS n FROM interpretations").fetchone()["n"]
            )

    def delete_prompt_version_sync(self, prompt_version: int) -> int:
        """Retire every entry from one prompt version.

        The one bulk operation this table has, and the reason the key's parts are stored
        as columns rather than only inside the key string.
        """
        with self._db.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM interpretations WHERE prompt_version = ?", (prompt_version,)
            )
            return cursor.rowcount


class NullSharedCache:
    """The shared tier, which is deliberately not implemented.

    Always misses, accepts every write and keeps none. ADR-0004: under one user there is
    nobody to share with, and the canonical-entry design in the original specification had
    a flaw worth fixing before building rather than after — whichever installation
    generated an entry first would fix its quality for everyone.

    What this class buys is that the chain around it is real. Swapping in a shared cache
    later changes this one binding and nothing else.
    """

    name = "shared"

    async def get(self, key: CacheKey) -> CachedValue | None:
        return None

    async def put(self, key: CacheKey, value: CachedValue) -> None:
        return None
