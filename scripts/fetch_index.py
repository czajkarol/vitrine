#!/usr/bin/env python
"""Merge a published index export into the local database.

    uv run python scripts/fetch_index.py --url https://.../vitrine-index.sqlite
    uv run python scripts/fetch_index.py --url https://... --sha256 <digest>
    uv run python scripts/fetch_index.py --file dist/vitrine-index.sqlite

The alternative to a 30-minute walk of AIC's collection, which is why it exists: see
ADR-0011. It writes only the corpus tables, so preferences, history, favourites and a
pasted API key all survive — `app/repositories/corpus.py` holds the allow-list that makes
that true.

**A download is checked before it is opened, and opened before it is merged.** The
transport must be HTTPS, the response must declare a length, that length must be within
the bounds an index can plausibly have, and the bytes that arrive must be a SQLite file
with exactly the tables an export has. `--sha256` is the check worth using when the
publisher offers a digest, because it is the only one that says the file is *the* file
rather than merely a well-formed one.
"""

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

# Running this as a script rather than a module, so the package has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.repositories.corpus import CorpusError, describe_export, merge_corpus
from app.repositories.database import Database

logger = logging.getLogger("fetch_index")

# A SQLite file smaller than this cannot hold a corpus, and one larger than this is not
# something to write to somebody's disk without them saying so. Both are bounds on
# obvious nonsense rather than a guess at the real size — a full export is ~58MB today.
MIN_DOWNLOAD_BYTES = 1_000_000
MAX_DOWNLOAD_BYTES = 500_000_000

DOWNLOAD_TIMEOUT_SECONDS = 120.0
CHUNK_BYTES = 1 << 20

# Its own string, not `AIC_USER_AGENT`. That one carries a contact address the owner gave
# to the Art Institute so they could get in touch about our traffic, and an export can be
# hosted anywhere; handing it to a third party is not what it was configured for.
USER_AGENT = "vitrine index fetcher (https://github.com/)"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        # Not pedantry: this file is written straight into the database the app reads, and
        # over plaintext anyone on the path chooses its contents.
        raise CorpusError(f"refusing a non-HTTPS URL: {url}")
    if not parsed.netloc:
        raise CorpusError(f"not a URL: {url}")


def download(url: str, destination: Path, expected_sha256: str | None) -> Path:
    """Stream `url` to `destination`, refusing anything it cannot vouch for first."""
    _check_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)

    digest = hashlib.sha256()
    written = 0
    headers = {"User-Agent": USER_AGENT}

    with (
        httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS) as client,
        client.stream("GET", url, headers=headers) as response,
    ):
        # Redirects are followed — a GitHub release asset is always one — so the
        # scheme is checked again on wherever we actually ended up.
        _check_url(str(response.url))
        response.raise_for_status()

        declared = response.headers.get("content-length")
        if declared is None or not declared.isdigit():
            raise CorpusError(
                "the server did not declare a Content-Length, so there is no size to "
                "verify against; download it by hand and use --file"
            )
        size = int(declared)
        if not MIN_DOWNLOAD_BYTES <= size <= MAX_DOWNLOAD_BYTES:
            raise CorpusError(
                f"declared size {size / 1_000_000:.1f} MB is outside the plausible "
                f"range for an index export"
            )
        logger.info("Downloading %.1f MB from %s", size / 1_000_000, response.url.host)

        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(CHUNK_BYTES):
                written += len(chunk)
                if written > size:
                    # A body longer than it said it would be is a reason to stop
                    # rather than a curiosity, and stopping mid-stream is what keeps
                    # MAX_DOWNLOAD_BYTES from being advisory.
                    raise CorpusError("the response is longer than its Content-Length")
                digest.update(chunk)
                handle.write(chunk)

    if written != size:
        raise CorpusError(f"download stopped short: {written} bytes of {size}")

    actual = digest.hexdigest()
    if expected_sha256 and actual.lower() != expected_sha256.strip().lower():
        partial.unlink(missing_ok=True)
        raise CorpusError(f"sha256 mismatch: expected {expected_sha256}, got {actual}")
    logger.info("sha256 %s%s", actual, " (verified)" if expected_sha256 else "")

    partial.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="an HTTPS URL to a published export")
    source.add_argument("--file", type=Path, help="an export already on disk")
    parser.add_argument(
        "--sha256", help="the digest the publisher gives for the file; checked before merging"
    )
    parser.add_argument(
        "--keep",
        type=Path,
        default=Path("dist/vitrine-index.sqlite"),
        help="where a downloaded export is written (default: dist/vitrine-index.sqlite)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what the export holds and merge nothing",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    settings = get_settings()
    try:
        if args.url:
            export_path = download(args.url, args.keep, args.sha256)
        else:
            export_path = args.file
            # A digest given with --file is checked too. The flag means "this is the file
            # I was promised", and it would mean nothing if half the ways in ignored it.
            if args.sha256:
                actual = sha256_of(export_path)
                if actual.lower() != args.sha256.strip().lower():
                    raise CorpusError(f"sha256 mismatch: expected {args.sha256}, got {actual}")
                logger.info("sha256 %s (verified)", actual)
        summary = describe_export(export_path)
        logger.info(
            "%s: %d artworks, %d term rows, %d facet rows, %.1f MB",
            summary.path.name,
            summary.artworks,
            summary.rows["artwork_terms"],
            summary.rows["artwork_facets"],
            summary.size_bytes / 1_000_000,
        )
        if args.dry_run:
            logger.info("--dry-run: nothing merged")
            return

        result = merge_corpus(Database(settings.database_path), export_path)
    except CorpusError as exc:
        raise SystemExit(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise SystemExit(f"download failed: {exc}") from exc

    logger.info(
        "Merged into %s: %d artworks in, %d new, %d now indexed. "
        "Preferences, history, favourites and credentials untouched.",
        settings.database_path,
        result.rows["artwork_index"],
        result.added,
        result.artworks_after,
    )


if __name__ == "__main__":
    main()
