"""Moving the corpus between databases: export it, and merge one back in.

The only module holding the SQL for that. `scripts/export_index.py` and
`scripts/fetch_index.py` are thin command-line wrappers over what is here, so that the two
halves of the round trip cannot drift apart and so that both can be tested without a
subprocess.

Why this exists at all is ADR-0011: the index is 64MB of derived cache and it lives in the
same file as an API key, so it is never committed. A published export is how somebody gets
a corpus without a 30-minute walk of AIC's collection.

**The allow-list is the safety property.** The export is built by copying named tables into
a *fresh* file, never by deleting from a copy of the live one. A table added to the schema
in six months is therefore absent from the export by default rather than present in it by
default, and the difference matters because one of the tables it might sit next to holds a
secret. `_assert_only_exported_tables` checks the result rather than trusting the loop.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.repositories.database import Database

CORPUS_TABLES: Final[tuple[str, ...]] = (
    "artwork_index",
    "artwork_terms",
    "artwork_facets",
)
"""The rebuildable corpus, in the order it must be written.

`artwork_index` first, and not alphabetically: the other two carry a foreign key to it with
`ON DELETE CASCADE`, and `INSERT OR REPLACE` on a parent row is a delete followed by an
insert. Merging the terms before the artworks would file them correctly and then have the
artworks cascade them straight back out.
"""

EXPORTED_TABLES: Final[tuple[str, ...]] = (*CORPUS_TABLES, "schema_migrations")
"""What an export file contains, and nothing else.

`schema_migrations` is not corpus; it is the export saying which schema it was built
against, so that a merge into an older database can refuse rather than write rows into
columns that do not exist yet.
"""

# An export with fewer artworks than this is almost certainly a `--limit` run somebody
# meant to keep to themselves, or a half-finished walk. Publishing one is not an error, so
# this is what `describe_export` reports against rather than something that refuses.
PLAUSIBLE_CORPUS_MINIMUM: Final[int] = 1_000


class CorpusError(RuntimeError):
    """A transfer that must not proceed: a missing table, a shape nobody recognises, an
    export built by a newer schema than the database receiving it."""


@dataclass(frozen=True)
class ExportResult:
    path: Path
    rows: dict[str, int]
    size_bytes: int


@dataclass(frozen=True)
class MergeResult:
    rows: dict[str, int]
    """Rows read out of the export, per table."""

    artworks_before: int
    artworks_after: int

    @property
    def added(self) -> int:
        """Artworks the target did not have. The rest were refreshed in place."""
        return self.artworks_after - self.artworks_before


@dataclass(frozen=True)
class ExportSummary:
    """What is inside a file before anything is merged out of it.

    Read from the file itself, never from the name it arrived under or from what a
    download said it would be.
    """

    path: Path
    size_bytes: int
    rows: dict[str, int]
    migrations: tuple[str, ...]

    @property
    def artworks(self) -> int:
        return self.rows.get("artwork_index", 0)


@contextmanager
def _plain_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """A connection with no journal-mode or foreign-key opinions.

    Deliberately not `Database.connect`, which turns on WAL. An export is a file that gets
    uploaded, and a WAL database that is copied without its `-wal` sidecar is a database
    missing its most recent writes. The default rollback journal leaves one self-contained
    file, which is the entire deliverable.
    """
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _table_names(connection: sqlite3.Connection, schema: str = "main") -> set[str]:
    rows = connection.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row["name"] for row in rows}


def _definitions(connection: sqlite3.Connection, kind: str, schema: str = "src") -> list[str]:
    """The `CREATE` statements for the exported tables, taken from the source database.

    Copied rather than re-declared. Every column comment and `WITHOUT ROWID` clause in
    `migrations/` would otherwise have to be maintained a second time here, and a
    divergence would show up as a subtly different schema in a file people download.
    """
    placeholders = ", ".join("?" * len(EXPORTED_TABLES))
    rows = connection.execute(
        f"SELECT sql FROM {schema}.sqlite_master WHERE type = ? "
        f"AND tbl_name IN ({placeholders}) AND sql IS NOT NULL",
        (kind, *EXPORTED_TABLES),
    )
    return [row["sql"] for row in rows]


def _assert_only_exported_tables(connection: sqlite3.Connection) -> None:
    present = _table_names(connection)
    unexpected = present - set(EXPORTED_TABLES)
    if unexpected:
        # Cannot happen while the copy loop reads from EXPORTED_TABLES, which is the
        # point: this fires if somebody later adds a copy step and not a list entry.
        raise CorpusError(
            f"export would contain tables outside the allow-list: {sorted(unexpected)}"
        )
    missing = set(EXPORTED_TABLES) - present
    if missing:
        raise CorpusError(f"export is missing tables: {sorted(missing)}")


def export_corpus(source: Database, destination: Path) -> ExportResult:
    """Copy the corpus tables into a fresh, `VACUUM`ed file at `destination`.

    The source is opened read-write because SQLite cannot read a WAL database read-only
    without being able to touch its shared-memory file, and a display may well be running.
    Nothing here writes to it.
    """
    if not source.path.exists():
        raise CorpusError(f"no database at {source.path}; build an index first")

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Written under a temporary name and renamed at the end. An export that was interrupted
    # is then absent rather than present-but-short, because the failure mode this guards
    # against is uploading a truncated one.
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)

    rows: dict[str, int] = {}
    with _plain_connection(partial) as connection:
        connection.execute("ATTACH DATABASE ? AS src", (str(source.path),))
        try:
            for statement in _definitions(connection, "table"):
                connection.execute(statement)
            _assert_only_exported_tables(connection)

            for table in EXPORTED_TABLES:
                connection.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table}")
                rows[table] = connection.execute(
                    f"SELECT count(*) AS n FROM main.{table}"
                ).fetchone()["n"]

            # Indexes after the rows, which is both faster and the only order in which
            # SQLite has to sort each index once instead of maintaining it per insert.
            for statement in _definitions(connection, "index"):
                connection.execute(statement)

            connection.commit()
        finally:
            # SQLite refuses to DETACH inside a transaction, and the failure path arrives
            # here with the implicit one still open. After the commit above this is a
            # no-op; after an error it is the rollback that was wanted anyway.
            connection.rollback()
            connection.execute("DETACH DATABASE src")

        # VACUUM refuses to run inside a transaction, hence the commit above. It is what
        # takes the copy down to its published size: the pages arrive in insertion order
        # and this rewrites the file without the slack.
        connection.execute("VACUUM")

    partial.replace(destination)
    return ExportResult(path=destination, rows=rows, size_bytes=destination.stat().st_size)


def describe_export(path: Path) -> ExportSummary:
    """Read what a file actually is, and refuse anything that is not an export.

    Called before a merge and after a download. A file that arrived over the network is
    checked here rather than trusted for its `Content-Length` or its name.
    """
    if not path.exists():
        raise CorpusError(f"no such file: {path}")
    if path.stat().st_size == 0:
        raise CorpusError(f"{path} is empty")

    try:
        with _plain_connection(path) as connection:
            # The first thing that touches a page, and so the first thing that fails on a
            # file that is not SQLite at all — an HTML error page saved under a .sqlite
            # name is the ordinary way a download goes wrong.
            present = _table_names(connection)
            unexpected = present - set(EXPORTED_TABLES)
            missing = set(EXPORTED_TABLES) - present
            if missing or unexpected:
                raise CorpusError(
                    f"{path} is not a vitrine index export "
                    f"(missing {sorted(missing)}, unexpected {sorted(unexpected)})"
                )
            rows = {
                table: connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in EXPORTED_TABLES
            }
            migrations = tuple(
                row["name"]
                for row in connection.execute("SELECT name FROM schema_migrations ORDER BY name")
            )
    except sqlite3.DatabaseError as exc:
        raise CorpusError(f"{path} is not a readable SQLite database: {exc}") from exc

    return ExportSummary(
        path=path, size_bytes=path.stat().st_size, rows=rows, migrations=migrations
    )


def merge_corpus(target: Database, export_path: Path) -> MergeResult:
    """Merge an export into `target`, touching nothing but the corpus tables.

    `preferences`, `history`, `credentials`, `artwork_feedback`, `interpretations` and
    `ai_usage` are not in `EXPORTED_TABLES` and so are not named by any statement here.
    Somebody's favourites and their pasted API key survive an index they downloaded.
    """
    summary = describe_export(export_path)

    # Bring the target up to the schema this code expects before comparing, so that a
    # first-ever fetch into a database that has never been opened by the app works.
    target.migrate()

    with target.connect() as connection:
        applied = {row["name"] for row in connection.execute("SELECT name FROM schema_migrations")}
        ahead = sorted(set(summary.migrations) - applied)
        if ahead:
            raise CorpusError(
                f"{export_path.name} was built against migrations this checkout does not have "
                f"({', '.join(ahead)}); update vitrine before fetching it"
            )

        before = connection.execute("SELECT count(*) AS n FROM artwork_index").fetchone()["n"]
        connection.execute("ATTACH DATABASE ? AS src", (str(export_path),))
        try:
            for table in CORPUS_TABLES:
                connection.execute(f"INSERT OR REPLACE INTO main.{table} SELECT * FROM src.{table}")
            after = connection.execute("SELECT count(*) AS n FROM artwork_index").fetchone()["n"]
            connection.commit()
        finally:
            # As in export_corpus: DETACH cannot run inside the implicit transaction the
            # inserts opened, and on the failure path that transaction is still open.
            connection.rollback()
            connection.execute("DETACH DATABASE src")

    return MergeResult(rows=summary.rows, artworks_before=before, artworks_after=after)
