#!/usr/bin/env python
"""Populate the local artwork index by walking the AIC collection.

Never runs on the request path. See ADR-0003 for why the index exists at all, and
`docs/aic-api.md` for why this uses `/artworks` rather than `/artworks/search`: the search
endpoint refuses anything past 1,000 records, while the plain listing endpoint paginates
the whole collection.

    uv run python scripts/build_index.py --limit 5000
    uv run python scripts/build_index.py            # the whole collection, ~22 minutes

Resumable and idempotent: progress is recorded after every page, a re-run picks up where it
stopped, and rows are upserted rather than inserted.
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Running this as a script rather than a module, so the package has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import Settings, get_settings
from app.domain.indexing import is_indexable
from app.providers.aic.client import MAX_LIMIT, AicClient, AicError
from app.repositories.artwork_index import ArtworkIndexRepository
from app.repositories.database import Database
from app.repositories.preferences import PreferencesRepository
from app.services.selection import IIIF_BASE_KEY

logger = logging.getLogger("build_index")

# AIC asks for no more than one request per second from a single-threaded scraper
# (docs/aic-api.md). The client's own 55/min limiter is a ceiling, not this courtesy.
REQUEST_INTERVAL_SECONDS = 1.0

# Where the walk got to, so a re-run resumes instead of starting over.
PROGRESS_KEY = "index_last_page"


async def build(settings: Settings, limit: int | None, restart: bool) -> int:
    database = Database(settings.database_path)
    database.migrate()

    index = ArtworkIndexRepository(database)
    preferences = PreferencesRepository(database)

    start_page = 1
    if restart:
        await preferences.set(PROGRESS_KEY, "0")
    else:
        recorded = await preferences.get(PROGRESS_KEY)
        if recorded and recorded.isdigit():
            start_page = int(recorded) + 1
            if start_page > 1:
                logger.info("Resuming from page %d", start_page)

    seen = 0
    kept = 0
    page = start_page
    total_pages: int | None = None

    async with AicClient(settings) as client:
        while True:
            started = time.monotonic()
            try:
                result = await client.list_artworks(page=page, limit=MAX_LIMIT)
            except AicError as exc:
                # Stop rather than spin. Progress is recorded, so re-running resumes here.
                logger.error("Stopping at page %d: %s", page, exc)
                break

            if not result.artworks:
                logger.info("Page %d came back empty; the walk is finished", page)
                break

            if result.iiif_base:
                await preferences.set(IIIF_BASE_KEY, result.iiif_base)
            total_pages = result.total_pages or total_pages

            eligible = [a for a in result.artworks if is_indexable(a)]
            await index.upsert_many(eligible)

            seen += len(result.artworks)
            kept += len(eligible)
            await preferences.set(PROGRESS_KEY, str(page))

            logger.info(
                "page %d/%s: %d records, %d indexable (running total: %d kept of %d)",
                page,
                total_pages or "?",
                len(result.artworks),
                len(eligible),
                kept,
                seen,
            )

            if limit is not None and seen >= limit:
                logger.info("Reached the --limit of %d records", limit)
                break
            if total_pages is not None and page >= total_pages:
                logger.info("Reached the last page")
                break

            page += 1
            # Measured from the start of the request, so slow responses do not add to the
            # delay — the intent is a rate, not a gap.
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(REQUEST_INTERVAL_SECONDS - elapsed, 0))

    total = await index.count()
    logger.info("Done. Kept %d of %d records this run; index now holds %d", kept, seen, total)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="stop after roughly this many records"
    )
    parser.add_argument(
        "--restart", action="store_true", help="ignore saved progress and walk from page 1"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )
    asyncio.run(build(get_settings(), args.limit, args.restart))


if __name__ == "__main__":
    main()
