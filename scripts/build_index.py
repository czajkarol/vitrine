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
from app.domain.scoring import explain, score
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


async def rescore(settings: Settings) -> int:
    """Recompute every row's curated score.

    A separate pass from the crawl on purpose: retuning a weight in `domain/scoring.py`
    should not mean walking AIC again.
    """
    database = Database(settings.database_path)
    database.migrate()
    index = ArtworkIndexRepository(database)

    written = 0
    for batch in index.iter_for_scoring_sync():
        await index.update_scores({artwork.id: score(artwork) for artwork in batch})
        written += len(batch)
        logger.info("scored %d rows", written)
    logger.info("Scoring complete: %d rows", written)
    return written


async def retag(settings: Settings) -> int:
    """Rebuild `artwork_facets` from the raw values already in SQLite.

    **No network at all.** The whole reason `artwork_terms` and `artwork_index.artwork_type`
    keep AIC's own values is that the canonical vocabulary is derived from them: changing
    `app/domain/vocabulary.py` and re-running this is the entire procedure for changing
    what the settings panel offers. See ADR-0009.

    Runs in seconds over the whole index, so it also runs automatically at the end of a
    crawl, next to the rescore — fresh rows arriving untagged would be invisible to every
    filter until someone remembered to do this by hand.
    """
    database = Database(settings.database_path)
    database.migrate()
    index = ArtworkIndexRepository(database)

    written, dropped = await index.retag()
    logger.info("Tagged %d facet rows across %d artworks", written, await index.count())
    for group, count in sorted(dropped.items()):
        if count:
            # Expected, and worth printing: these are the provenance terms and the
            # publication titles that DROPPED removes on purpose. A sudden change in the
            # number is the signal that AIC's vocabulary has moved under the map.
            logger.info("  %s: %d raw values dropped by the vocabulary", group, count)
    return written


async def explain_one(settings: Settings, artwork_id: int) -> None:
    """Print one artwork's score breakdown.

    The check on whether the scoring is too clever: if this does not make it obvious why
    A outranked B, the weights need simplifying, not tuning.
    """
    database = Database(settings.database_path)
    artwork = await ArtworkIndexRepository(database).get(artwork_id)
    if artwork is None:
        raise SystemExit(f"artwork {artwork_id} is not in the index")
    print(f"{artwork.title} — {artwork.artist_title or 'unattributed'}")
    print(f"  type={artwork.artwork_type_title!r} boosted={artwork.is_boosted}")
    print(explain(artwork).format())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="stop after roughly this many records"
    )
    parser.add_argument(
        "--restart", action="store_true", help="ignore saved progress and walk from page 1"
    )
    parser.add_argument(
        "--score-only", action="store_true", help="skip the crawl and just recompute scores"
    )
    parser.add_argument(
        "--retag",
        action="store_true",
        help="skip the crawl and rebuild the canonical facets from what is already indexed",
    )
    parser.add_argument(
        "--explain", type=int, metavar="ARTWORK_ID", help="print one artwork's score breakdown"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    settings = get_settings()
    if args.explain is not None:
        asyncio.run(explain_one(settings, args.explain))
        return
    if args.score_only:
        asyncio.run(rescore(settings))
        return
    if args.retag:
        asyncio.run(retag(settings))
        return

    asyncio.run(build(settings, args.limit, args.restart))
    # Fresh rows arrive unscored and untagged, so curated mode and every filter would miss
    # them until someone remembered to run these by hand. Both are local and quick.
    asyncio.run(rescore(settings))
    asyncio.run(retag(settings))


if __name__ == "__main__":
    main()
