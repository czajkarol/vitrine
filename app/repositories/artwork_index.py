"""Reads and writes for `artwork_index`. The only module holding its SQL."""

import asyncio
import sqlite3
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Final

from app.domain.artwork import Artwork, Color, Thumbnail
from app.domain.vocabulary import FACET_GROUPS, FacetGroup, facet_for, facets_for
from app.repositories.database import Database
from app.repositories.feedback import hidden_clause

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
            self._replace_facets(connection, artworks)
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

    @staticmethod
    def _replace_facets(connection: sqlite3.Connection, artworks: Sequence[Artwork]) -> None:
        """Tag the rows being written, in the same transaction that writes them.

        Not left to `--retag`: a crawl that wrote rows and did not tag them would leave
        them in the index but invisible to every filter until someone remembered, and
        "the artwork exists but no filter can find it" is a bug nobody would think to
        look for. `--retag` is for when the *vocabulary* changes, not for catching up.

        Delete-then-insert for the same reason as the terms above: a facet can stop
        applying when a term is removed upstream, and an upsert would leave it behind.
        """
        connection.executemany(
            "DELETE FROM artwork_facets WHERE artwork_id = ?",
            [(artwork.id,) for artwork in artworks],
        )
        pairs: list[tuple[int, str]] = []
        for artwork in artworks:
            by_group: dict[FacetGroup, tuple[str, ...]] = {
                "type": (artwork.artwork_type_title,) if artwork.artwork_type_title else (),
                "style": tuple(artwork.style_titles),
                "subject": tuple(artwork.subject_titles),
            }
            for group, values in by_group.items():
                pairs.extend((artwork.id, key) for key in facets_for(group, values))
        connection.executemany(
            "INSERT OR IGNORE INTO artwork_facets (artwork_id, facet) VALUES (?, ?)", pairs
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

    @staticmethod
    def _facet_clauses(
        include: Sequence[Sequence[str]], exclude: Sequence[str], id_column: str = "id"
    ) -> tuple[list[str], list[object]]:
        """WHERE fragments for a facet selection. One query shape for all three groups.

        That is what migration 008 bought: before it, artwork type was a column and style
        and subject were a join table, so this had to be written twice and kept in step.

        **`include` is a list of alternative-sets, one per group: OR inside, AND between.**
        Until M13 a group held one facet and inclusion was a flat AND over all of them.
        Allowing several at once inside a group had to change the operator, not just the
        arity: `type.painting AND type.print` is empty by construction — nothing is both —
        where `type.painting OR type.print` is the filter anyone means by ticking two boxes.
        Across groups it stays AND, because "a Japanese print" narrows in the way a person
        expects.

        Exclusion stays a single NOT IN over everything excluded, from any group: excluding
        several things at once is one condition, not several.

        `id_column` is the artwork id in whatever the caller is selecting from: `id` in
        `artwork_index`, `artwork_id` when counting inside `artwork_facets` itself. It is
        never user input — the callers below pass literals.
        """
        where: list[str] = []
        params: list[object] = []
        for group in include:
            facets = [facet for facet in group if facet]
            if not facets:
                continue
            placeholders = ",".join("?" for _ in facets)
            where.append(
                f"{id_column} IN (SELECT artwork_id FROM artwork_facets "
                f"WHERE facet IN ({placeholders}))"
            )
            params.extend(facets)
        if exclude:
            placeholders = ",".join("?" for _ in exclude)
            where.append(
                f"{id_column} NOT IN (SELECT artwork_id FROM artwork_facets "
                f"WHERE facet IN ({placeholders}))"
            )
            params.extend(exclude)
        return where, params

    def sample_sync(
        self,
        limit: int,
        curated: bool = False,
        facets: Sequence[Sequence[str]] = (),
        exclude: Sequence[str] = (),
        hidden: Sequence[int] = (),
    ) -> list[Artwork]:
        """A pool of candidates.

        Sampling here and applying the history penalty in `domain/selection.py` keeps the
        rule pure and testable; doing it in SQL would bury it in a query.

        Curated mode draws from the highest-scoring rows instead of the whole index. Rows
        scored NULL are excluded there rather than sorted to one end, because an unscored
        row is unranked, not bad — it just has not been through a scoring pass yet.

        `facets` is one sequence of canonical facet keys per group — OR inside a group,
        AND between groups; `exclude` removes anything carrying any of the keys in it.
        Both go through `artwork_facets`, artwork type included — see `_facet_clauses`.
        """
        where, params = self._facet_clauses(facets, exclude)
        # Hidden artworks are excluded in every mode, including plain random. `X` means
        # never show me this again, and a mode switch is not a change of mind about it.
        hidden_sql, hidden_params = hidden_clause(hidden)
        if hidden_sql:
            where.append(hidden_sql)
            params.extend(hidden_params)
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
        facets: Sequence[Sequence[str]] = (),
        exclude: Sequence[str] = (),
        hidden: Sequence[int] = (),
    ) -> list[Artwork]:
        return await asyncio.to_thread(self.sample_sync, limit, curated, facets, exclude, hidden)

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

    # --- facets -------------------------------------------------------------------

    def retag_sync(self, batch: int = 5000) -> tuple[int, dict[str, int]]:
        """Rebuild `artwork_facets` from the raw values already in SQLite.

        No network. It reads `artwork_index.artwork_type` and `artwork_terms`, applies
        `domain.vocabulary`, and rewrites the table wholesale — which is the point of
        keeping the raw values: changing the vocabulary is an edit to one pure module and
        one re-run of this.

        Wholesale rather than incremental because a facet can *stop* existing when the map
        changes, and an incremental update would leave it behind forever with nothing
        pointing at it.

        :returns: how many facet rows were written, and how many raw tags each group threw
            away. Nothing can be *unmapped* — a value with no rule of its own derives its
            own facet — so the only number worth reporting is what `DROPPED` removed, and
            it is worth reporting because a sudden change in it means AIC's vocabulary has
            moved under the map.
        """
        written = 0
        dropped: dict[str, int] = dict.fromkeys(FACET_GROUPS, 0)
        with self._db.connect() as connection:
            connection.execute("DELETE FROM artwork_facets")
            offset = 0
            while True:
                rows = connection.execute(
                    "SELECT id, artwork_type FROM artwork_index ORDER BY id LIMIT ? OFFSET ?",
                    (batch, offset),
                ).fetchall()
                if not rows:
                    break
                ids = [row["id"] for row in rows]
                raw = self._raw_terms_by_group(connection, ids)
                for row in rows:
                    if row["artwork_type"]:
                        raw.setdefault(row["id"], {}).setdefault("type", []).append(
                            row["artwork_type"]
                        )
                pairs: list[tuple[int, str]] = []
                for artwork_id in ids:
                    by_group = raw.get(artwork_id, {})
                    for group in FACET_GROUPS:
                        values = by_group.get(group, [])
                        keys = facets_for(group, values)
                        pairs.extend((artwork_id, key) for key in keys)
                        # Not len(values) - len(keys): merging also reduces the count, and
                        # a merge is not a loss. Only a value with no facet at all is.
                        dropped[group] += sum(
                            1 for value in values if facet_for(group, value) is None
                        )
                connection.executemany(
                    "INSERT OR IGNORE INTO artwork_facets (artwork_id, facet) VALUES (?, ?)",
                    pairs,
                )
                written += len(pairs)
                offset += len(rows)
        return written, dropped

    @staticmethod
    def _raw_terms_by_group(
        connection: sqlite3.Connection, artwork_ids: Sequence[int]
    ) -> dict[int, dict[str, list[str]]]:
        """The raw style and subject values for a batch, grouped the way facets are."""
        if not artwork_ids:
            return {}
        placeholders = ",".join("?" for _ in artwork_ids)
        rows = connection.execute(
            f"SELECT artwork_id, kind, value FROM artwork_terms "
            f"WHERE artwork_id IN ({placeholders})",
            list(artwork_ids),
        ).fetchall()
        collected: dict[int, dict[str, list[str]]] = {}
        for row in rows:
            collected.setdefault(row["artwork_id"], {}).setdefault(row["kind"], []).append(
                row["value"]
            )
        return collected

    async def retag(self) -> tuple[int, dict[str, int]]:
        return await asyncio.to_thread(self.retag_sync)

    def facet_counts_sync(
        self,
        group: FacetGroup,
        include: Sequence[Sequence[str]] = (),
        exclude: Sequence[str] = (),
    ) -> dict[str, int]:
        """How many artworks sit behind each facet in one group.

        `include` and `exclude` constrain the count. Leave-one-out is the caller's job:
        pass the *other* groups' selections, not this one's, so choosing a style updates
        the subject counts without collapsing the style list you are standing in.

        Called with nothing constraining it, this is the unconstrained count that decides
        what is offered at all.
        """
        where, params = self._facet_clauses(include, exclude, id_column="artwork_id")
        clause = f" AND {' AND '.join(where)}" if where else ""
        # A prefix LIKE on the indexed facet column is a range scan, not a table scan:
        # the group is the first segment of every key, which is why keys are built that
        # way rather than the group living in a column of its own.
        sql = (
            "SELECT facet, COUNT(*) AS n FROM artwork_facets "
            f"WHERE facet LIKE ?{clause} "
            "GROUP BY facet ORDER BY n DESC, facet"
        )
        with self._db.connect() as connection:
            rows = connection.execute(sql, [f"{group}.%", *params]).fetchall()
        return {row["facet"]: int(row["n"]) for row in rows}

    async def facet_counts(
        self,
        group: FacetGroup,
        include: Sequence[Sequence[str]] = (),
        exclude: Sequence[str] = (),
    ) -> dict[str, int]:
        return await asyncio.to_thread(self.facet_counts_sync, group, include, exclude)

    def facets_and_scores_sync(
        self, artwork_ids: Sequence[int]
    ) -> tuple[dict[int, tuple[str, ...]], dict[int, float | None]]:
        """The facets and curated score of a batch of candidates.

        For the personal mode, which ranks in Python rather than in SQL: the affinity
        profile changes with every like and belongs in `domain/`, not in a query that
        would have to be rebuilt to hold it.
        """
        if not artwork_ids:
            return {}, {}
        placeholders = ",".join("?" for _ in artwork_ids)
        ids = list(artwork_ids)
        with self._db.connect() as connection:
            facet_rows = connection.execute(
                f"SELECT artwork_id, facet FROM artwork_facets "
                f"WHERE artwork_id IN ({placeholders})",
                ids,
            ).fetchall()
            score_rows = connection.execute(
                f"SELECT id, score FROM artwork_index WHERE id IN ({placeholders})", ids
            ).fetchall()
        facets: dict[int, list[str]] = {}
        for row in facet_rows:
            facets.setdefault(row["artwork_id"], []).append(row["facet"])
        return (
            {key: tuple(values) for key, values in facets.items()},
            {row["id"]: row["score"] for row in score_rows},
        )

    async def facets_and_scores(
        self, artwork_ids: Sequence[int]
    ) -> tuple[dict[int, tuple[str, ...]], dict[int, float | None]]:
        return await asyncio.to_thread(self.facets_and_scores_sync, artwork_ids)

    def facet_row_count_sync(self) -> int:
        with self._db.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS n FROM artwork_facets").fetchone()
        return int(row["n"])

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
