# 0003. Build a local artwork index

Status: Accepted
Date: 2026-09-02

> **Postscript, 2026-09-03.** Two premises below were measured against the live API and were
> wrong; the decision is unaffected and stands. The search cap is **1,000** records, not 10,000
> — which strengthens the argument. And the plain `/artworks` listing endpoint is **not capped**
> at all, so the index is built by walking it at 1 req/s rather than by downloading the nightly
> data dump. Details in `docs/aic-api.md`.

> **Second postscript, 2026-09-03, checked against the built app.** One line below is stronger
> than what was built, and in the app's favour: "AIC is called only to refresh detail for the one
> artwork about to be shown" describes a refresh that does not happen. The index row carries
> everything the display needs, so serving an indexed artwork makes no AIC API call at all —
> visible in `/api/stats`, where `aic.requests` stays at zero through a rotation. AIC is reached
> only when there is no index (`_from_aic`), and by the image proxy of ADR-0008.

> **Third postscript, 2026-09-04, at the end of M12.** The decision stands; one cost below is
> no longer the only option. "An indexing script that must be resumable and idempotent" was
> written when walking AIC was the sole way to obtain a corpus, which put a 30-minute crawl —
> and the owner's approval for it — between a clean clone and a working index. The corpus can
> now be exported to a file and merged into another database instead: about a second, and no
> AIC traffic at all. The walk remains how a corpus is *created* and refreshed. See ADR-0011.

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
