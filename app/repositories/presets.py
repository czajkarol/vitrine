"""Saved filter combinations. The only module holding `filter_presets`'s SQL.

A preset is a museum plus the three inclusion lists plus the exclusion list — exactly what
the panel already assembles as its current selection, under a name. Nothing about a mode
or an interval: those are how the display behaves, not what it is showing.

See migration 012 for why this is a table rather than a blob in `preferences`, and for why
the facet lists are comma-separated rather than JSON. Two things worth repeating here:

**A preset holds facet keys, and a facet key can stop existing.** There is no foreign key
and no validation against the vocabulary on the way in or out, deliberately. A rebuilt
index, a change to the merge rules in `domain/vocabulary.py`, or a switch of museum can all
leave a saved key with nothing behind it. Dropping such a key here would silently *widen*
what the preset means — "Japanese prints" quietly becoming "prints" — which is the one
failure the whole Explore path is written to avoid (`_included_facets` in `api/routes.py`
takes the same position for the same reason). So the key is kept, applied, and matches
nothing, and the panel says which of a preset's filters the index no longer offers.

**Saving over a name replaces it.** Names are how the user refers to these, so they are
unique, and re-saving an adjusted preset under the same name is the ordinary case rather
than a conflict to be reported.
"""

import asyncio
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from app.repositories.database import Database

SEPARATOR: Final[str] = ","
"""How a facet list is stored. The same encoding `preferences` uses, safe for the same
reason: a facet key cannot contain a comma. `domain/vocabulary.py`."""

MAX_PRESETS: Final[int] = 30
"""How many a user may keep. Not a storage limit — thirty rows is nothing — but a limit on
a list somebody has to read down. Saving over an existing name is not a new preset and is
never refused by this."""

MAX_NAME_LENGTH: Final[int] = 60
"""Long enough for a phrase, short enough to sit in the panel without wrapping twice."""


class PresetError(RuntimeError):
    """A save that cannot proceed: no name, or no room for another one."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Preset:
    """One saved selection. The lists are facet keys, in the order they were saved."""

    id: int
    name: str
    museum: str
    artwork_type: tuple[str, ...]
    style: tuple[str, ...]
    subject: tuple[str, ...]
    exclude: tuple[str, ...]
    updated_at: str


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(part for part in (value or "").split(SEPARATOR) if part)


def _join(values: Sequence[str] | None) -> str:
    # Deduplicated on the way in, because a list with the same facet twice means the same
    # thing as one with it once and reads as a bug when it comes back out.
    seen: list[str] = []
    for value in values or ():
        if value and value not in seen:
            seen.append(value)
    return SEPARATOR.join(seen)


def _to_preset(row: sqlite3.Row) -> Preset:
    return Preset(
        id=row["id"],
        name=row["name"],
        museum=row["museum"],
        artwork_type=_split(row["artwork_type"]),
        style=_split(row["style"]),
        subject=_split(row["subject"]),
        exclude=_split(row["exclude"]),
        updated_at=row["updated_at"],
    )


class PresetRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def list_sync(self) -> list[Preset]:
        """Every preset, ordered the way somebody reads a list of names they wrote."""
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM filter_presets ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [_to_preset(row) for row in rows]

    async def list_all(self) -> list[Preset]:
        return await asyncio.to_thread(self.list_sync)

    def save_sync(
        self,
        name: str,
        *,
        museum: str,
        artwork_type: Sequence[str] | None = None,
        style: Sequence[str] | None = None,
        subject: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> Preset:
        """Save under a name, replacing any preset already using it.

        The cap is checked against a *new* name only. Re-saving an existing one at the
        limit is somebody adjusting what they already have, and refusing that would be
        refusing the thing the limit is not about.
        """
        clean = name.strip()
        if not clean:
            raise PresetError("preset_unnamed")
        clean = clean[:MAX_NAME_LENGTH]
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self._db.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM filter_presets WHERE name = ?", (clean,)
            ).fetchone()
            if existing is None:
                count = connection.execute("SELECT COUNT(*) AS n FROM filter_presets").fetchone()
                if count["n"] >= MAX_PRESETS:
                    raise PresetError("preset_limit_reached")
            connection.execute(
                "INSERT INTO filter_presets"
                " (name, museum, artwork_type, style, subject, exclude, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET"
                "   museum = excluded.museum,"
                "   artwork_type = excluded.artwork_type,"
                "   style = excluded.style,"
                "   subject = excluded.subject,"
                "   exclude = excluded.exclude,"
                "   updated_at = excluded.updated_at",
                (
                    clean,
                    museum,
                    _join(artwork_type),
                    _join(style),
                    _join(subject),
                    _join(exclude),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM filter_presets WHERE name = ?", (clean,)
            ).fetchone()
        return _to_preset(row)

    async def save(
        self,
        name: str,
        *,
        museum: str,
        artwork_type: Sequence[str] | None = None,
        style: Sequence[str] | None = None,
        subject: Sequence[str] | None = None,
        exclude: Sequence[str] | None = None,
    ) -> Preset:
        return await asyncio.to_thread(
            self.save_sync,
            name,
            museum=museum,
            artwork_type=artwork_type,
            style=style,
            subject=subject,
            exclude=exclude,
        )

    def delete_sync(self, preset_id: int) -> bool:
        """Forget one. Returns whether there was anything to forget."""
        with self._db.connect() as connection:
            cursor = connection.execute("DELETE FROM filter_presets WHERE id = ?", (preset_id,))
        return cursor.rowcount > 0

    async def delete(self, preset_id: int) -> bool:
        return await asyncio.to_thread(self.delete_sync, preset_id)
