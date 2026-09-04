#!/usr/bin/env python
"""Write a publishable copy of the artwork index.

    uv run python scripts/export_index.py
    uv run python scripts/export_index.py --output dist/vitrine-index.sqlite --force

The corpus tables only — `artwork_index`, `artwork_terms`, `artwork_facets` — plus
`schema_migrations` so the file can say which schema it was built against. Everything else
in `data/vitrine.db` is either user state or, in the case of `credentials`, an API key, and
none of it is copied. See `docs/data.md` for the table-by-table position and ADR-0011 for
why the result is a release asset rather than something committed.

No network. This reads SQLite and writes SQLite.
"""

import argparse
import logging
import sys
from pathlib import Path

# Running this as a script rather than a module, so the package has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.repositories.corpus import (
    PLAUSIBLE_CORPUS_MINIMUM,
    CorpusError,
    export_corpus,
)
from app.repositories.database import Database

logger = logging.getLogger("export_index")

DEFAULT_OUTPUT = Path("dist/vitrine-index.sqlite")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"where to write the export (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing file at --output"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    output: Path = args.output
    if output.exists() and not args.force:
        raise SystemExit(f"{output} already exists; pass --force to overwrite it")

    settings = get_settings()
    try:
        result = export_corpus(Database(settings.database_path), output)
    except CorpusError as exc:
        raise SystemExit(str(exc)) from exc

    for table, count in result.rows.items():
        logger.info("  %-18s %8d rows", table, count)
    logger.info(
        "Wrote %s — %.1f MB, %d artworks",
        result.path,
        result.size_bytes / 1_000_000,
        result.rows["artwork_index"],
    )

    artworks = result.rows["artwork_index"]
    if artworks < PLAUSIBLE_CORPUS_MINIMUM:
        # Not an error: a small export is a legitimate thing to make for a test. It is
        # worth saying out loud because the file it produces is indistinguishable by name
        # from a full one, and the mistake it prevents is publishing a --limit run.
        logger.warning(
            "Only %d artworks. A full walk indexes tens of thousands — is this a --limit run?",
            artworks,
        )


if __name__ == "__main__":
    main()
