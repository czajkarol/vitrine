# 0003. Build a local artwork index

Status: Accepted
Date: 2026-09-02

## Context

The application needs to pick a random artwork matching a set of filters, repeatedly, for hours.

The AIC API cannot support that directly. Its search endpoints refuse any request past 10,000
records through any combination of `limit` and `page`, `limit` itself caps at 100, and anonymous
clients are throttled to 60 requests per minute. Random selection by paginating to a random offset
would therefore only ever reach the same top ten thousand relevance-ranked records, and fewer once
filters narrow the set.

Curated mode compounds this: a scoring system cannot rank a corpus it cannot enumerate.

AIC's own documentation points at the answer, recommending nightly JSON data dumps over API
scraping for bulk access, and asking that clients cache responses.

## Decision

Build a local index in SQLite. A script walks AIC — throttled to one request per second, or
reading a downloaded data dump — filters to public-domain works with usable images, computes a
score for each, and writes rows to `artwork_index`.

At runtime, artwork selection reads only from SQLite. AIC is called only to refresh detail for
the one artwork about to be shown.

## Alternatives considered

**Random page offsets within the 10,000 window.** Simple, and quietly wrong: the same small
slice of the collection forever, worse under filters, and one network round trip per artwork.

**Fetch a batch and shuffle it.** Same problem with extra steps.

**Ship a static curated list.** Removes the API integration that is half the point of the project.

## Consequences

Selection becomes instant, works offline, and stays far below the rate limit. Explore filters can
be validated against real counts before being offered. Curated scoring has a corpus to rank.

The cost is an extra artefact — the index — that can go stale, and an indexing script that must
be resumable and idempotent. Because AIC may unpublish or replace any image at any time, the
index is treated as a cache with a refresh cycle, and the display path tolerates a dead image by
skipping to the next artwork.
