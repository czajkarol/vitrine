"""SQLite connection handling and the migration runner.

Everything here is synchronous, because `sqlite3` is. Async callers go through the
`repositories.*` wrappers, which push each call onto a worker thread — see the note in
`app/CLAUDE.md` about not blocking the request path.
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

MIGRATIONS_DIR: Final[Path] = Path(__file__).resolve().parent / "migrations"


class Database:
    """Owns the database file and hands out connections.

    A connection per operation rather than one shared handle: `sqlite3` connections are
    not safe to move between threads, and every async repository call runs on whichever
    worker thread it lands on. Opening a connection is cheap, and this app reads roughly
    once every five minutes.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """A configured connection, committed on success and closed either way."""
        self.ensure_parent()
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        # WAL lets the indexing script write while the app reads, which is the whole
        # reason the script can be run against a live display.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        # Durability is worth less here than not stalling on every insert; the index is a
        # rebuildable cache, not a system of record.
        connection.execute("PRAGMA synchronous=NORMAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        """Apply every migration not yet recorded, in filename order.

        Numbered SQL files and a table of what has run. `docs/architecture.md` rules out
        Alembic for this, and for a handful of tables it would be the larger thing to
        maintain.
        """
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {
                row["name"] for row in connection.execute("SELECT name FROM schema_migrations")
            }

            for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if migration.name in applied:
                    continue
                logger.info("Applying migration %s", migration.name)
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)", (migration.name,)
                )
