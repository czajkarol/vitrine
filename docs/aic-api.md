# Art Institute of Chicago API

Everything here is marked **confirmed** or **unverified**. Confirmed means it was checked
against a live response, with the date. Do not build on anything unverified without checking
first — and when you do check, move it up and say so.

Base URL: `https://api.artic.edu/api/v1`

Live responses backing this document are committed in `tests/fixtures/aic/`.

---

## Limits and etiquette (confirmed 2026-09-03)

| Constraint | Value |
|---|---|
| Authentication | None. Public API, no key. |
| Throttle | 60 requests/minute per IP for anonymous users |
| `limit` per page | Max 100 (`limit=101` → `403 Invalid limit`), default 12 |
| **Search depth** | **`page × limit ≤ 1000`.** Past that: `403 Invalid number of results` |
| **Listing depth** | **Uncapped.** `/artworks` paginates the entire collection |
| Courtesy header | `AIC-User-Agent: vitrine (karolkczaj@gmail.com)` on every request |
| Scraping | Single thread, no more than 1 request/second, no parallel scrapers |
| Bulk data | Nightly JSON dumps at <https://github.com/art-institute-of-chicago/api-data> |

### The search cap is 1,000, not 10,000

Measured precisely: `limit=100&page=10` (records 901–1000) returns `200`; `page=11` returns
`403`. `limit=1&page=1000` returns `200`; `page=1001` returns `403`. The boundary is on the
product, not on either parameter alone.

This is ten times tighter than the figure this document previously carried. It makes ADR-0003's
conclusion stronger, not weaker.

### But `/artworks` is not capped, and that is how the index gets built

The cap applies to `/artworks/search` only. The plain listing endpoint paginates the whole
collection: 132,740 records, 1,328 pages at `limit=100`, and page 1,328 returns the final 40
rows. Walked to the end successfully on 2026-09-03.

The total moves. A few hours later the same endpoint reported **132,741**. Treat the figure as a
snapshot and read `pagination.total_pages` from the response rather than assuming a page count —
which is what `scripts/build_index.py` does. A recorded page is committed at
`tests/fixtures/aic/artwork_listing_page2.json` so the contract test notices if the shape moves.

So bulk indexing does **not** require the nightly data dumps. `scripts/build_index.py` can walk
`/artworks` at AIC's requested 1 req/s in roughly 22 minutes. ADR-0003 reaches the right
conclusion from two wrong premises; its consequences section stands.

`limit=0` returns only the `pagination` block — a cheap way to count matches for a filter
without transferring records. `/artworks/search?query[term][is_public_domain]=true&limit=0`
reports **62,046** public-domain works.

---

## Endpoints we use

```
GET /artworks?page=N&limit=100  Full-collection walk. Uncapped. This is the index source.
GET /artworks/search            Elasticsearch-backed. Capped at 1,000 records — see above.
GET /artworks?ids=1,2,3         Batch detail fetch — preferred over N single requests
GET /artworks/{id}              Single artwork. Unknown id → 404
GET /artwork-types              45 types. "Painting" is id 1. Use to build Explore filters.
GET /category-terms             11,026 terms, with a `subtype` field (subject / style / …)
```

### Always pass `fields=`

Not just for payload size. **A default `/artworks/search` response contains only seven fields:**
`id`, `title`, `api_link`, `api_model`, `is_boosted`, `thumbnail`, `_score`, `timestamp`.

It does **not** include `image_id` or `is_public_domain`. The public-domain hard filter and the
IIIF URL are both impossible to satisfy from a default search response, so a search without
`fields=` is useless to us. The listing endpoint behaves the same way.

Also note the default search ordering leads with non-public-domain works: the top result for an
unfiltered search is id `129884` (Alma Thomas), `is_public_domain: false`. Never rely on
ordering as a proxy for eligibility. Filter explicitly.

---

## Fields

### Term vocabularies, verified on `/artworks/27992` (2026-09-03)

Explore filters come from these. All confirmed present on a full artwork response; none are
returned unless named in `fields=`.

| Field | Example | Note |
|---|---|---|
| `artwork_type_title` | `Painting` | The 45-value vocabulary behind `/artwork-types`. This is what the app filters on. |
| `classification_title` | `oil on canvas` | **Not** the artwork type. A material/technique term. |
| `classification_titles` | `[oil on canvas, paint, oil paintings (visual works)]` | |
| `style_title` / `style_titles` | `Pointillism`, `[Pointillism, nineteenth century, …]` | |
| `subject_titles` | `[leisure, animals, landscape]` | 23 on this record |
| `term_titles` | 42 entries, all of the above pooled | |
| `category_titles` | `[Painting and Sculpture of Europe, Art Institute Icons, Essentials]` | Departments and curated sets |

**The name collision is the trap here.** `classification_title` sounds like the artwork type and
is not; it is closer to a medium. Filter on `artwork_type_title`. The local index column that
holds it is named `artwork_type` for exactly this reason — an earlier name of `classification`
invited the mistake.

Style and subject filters need `style_titles` and `subject_titles` indexed per artwork, which
means adding them to the crawl's `fields=` list and re-walking. Not done yet; the index currently
carries artwork type only.

### Confirmed present in search responses (2026-09-03)

| Field | Why it matters |
|---|---|
| `id`, `title`, `api_link` | Identity |
| `is_boosted` | AIC boosts its own "essentials" group. A free, honest curatorial signal — use it in Curated scoring rather than inventing one. |
| `thumbnail.lqip` | Base64 GIF blur placeholder, inline in the response. Paint it instantly, fade the real image in over it. Costs one extra network request: zero. |
| `thumbnail.alt_text` | Human-written visual description from the museum. Use for `alt=`, and as grounding context in AI prompts. |
| `thumbnail.width` / `height` | Real source dimensions, often thousands of px. Use for quality filtering and aspect-ratio scoring. |
| `_score`, `timestamp` | Relevance and last-update |

`thumbnail` itself is `null` when a work has no image. Model it as optional, not as a dict that
is always there.

### Confirmed on detail and listing responses (2026-09-03)

`image_id`, `alt_image_ids`, `artist_display`, `artist_title`, `date_display`,
`main_reference_number`, `classification_titles`, `style_ids`, `term_titles`,
`is_public_domain`, `description`, `short_description`, `credit_line`, `artwork_type_title`,
`artwork_type_id`, `boost_rank`, `dimensions`, `inscriptions`, `is_zoomable`,
`gallery_title`, `theme_titles`, `category_titles`.

### Previously unverified, now confirmed (2026-09-03)

Checked against `/artworks/27992` and `/artworks/search?limit=2`. All of these exist.

- **`color`** — real, on both detail and listing responses. Shape is
  `{"h": 59, "l": 52, "s": 12, "percentage": 0.0021, "population": 1217}`: HSL integers plus a
  population count, exactly as hoped. **Use it for the background tint**; the `lqip` fallback is
  not needed. It is `null` on works without an image.
- **`date_start` / `date_end`** — integers (`1884` / `1886`).
- **`is_on_view`** — bool. **`department_title`** — str. **`place_of_origin`** — str.
  **`medium_display`** — str. **`subject_titles`** — `list[str]`.
- **`style_titles`** — present. The `_titles` twin of `style_ids` does exist, and there are
  matching `material_titles`, `technique_titles`, `classification_titles`.

### Corpus shape, measured

On a random listing page of 100: 86 public domain, but only **45 with an `image_id`**. Roughly
45% of the collection is displayable, consistent with the 62,046 public-domain count. Budget for
the index being about half the raw record count, and filter on `image_id` presence at index time.

---

## Images (IIIF)

The API contains no image files. Images come from a separate IIIF Image API 2.0 service.

```
{config.iiif_url}/{image_id}/full/{width},/0/default.jpg
```

- `config.iiif_url` is returned on every API response (`https://www.artic.edu/iiif/2`).
  **Read it, never hardcode it.**
- Cached widths: `200`, `400`, `600`, `843`. Also `1686` for public-domain works.
- **Prefer `843`.** AIC's own site uses it, so it is the size most likely to be cached at their
  edge. An odd width means a cache miss and a slow first paint.
- Any image may be unpublished or replaced without notice. The display path must survive a dead
  image by advancing rather than showing a broken frame.

### Hotlinking is blocked by Cloudflare — see ADR-0008 (confirmed 2026-09-03)

This document previously stated that images could be loaded directly in the browser and that a
proxy must not be built. **That is no longer true.** `www.artic.edu` sits behind Cloudflare Bot
Management, which challenges requests an `<img>` tag cannot satisfy.

Server-side, deterministic over three trials per case:

| Request headers | Result |
|---|---|
| none | `403`, `cf-mitigated: challenge` |
| `AIC-User-Agent` only | `403`, `cf-mitigated: challenge` |
| browser `User-Agent` only | `403`, `cf-mitigated: challenge` |
| browser `User-Agent` **+** `AIC-User-Agent` | `200`, `image/jpeg`, `ACAO: *` |

The bypass requires a custom header, and **a browser cannot set a header on an `<img>` request.**
That is the whole problem in one sentence.

In a real browser, `<img>` + `decode()` from a `localhost` page, measured in one execution after
the browser had already solved the Cloudflare challenge and held a `cf_clearance` cookie:

```
PROXIED  same-origin /api/image: OK 843x565 (211ms)
DIRECT   artic.edu IIIF:         FAIL EncodingError (126ms)
CONTROL  placehold.co:           OK 300x200 (266ms)
```

The control rules out a local or CORS problem: unrelated cross-origin images load fine. The
clearance cookie does not carry to a cross-site subresource request.

**Caveat:** Cloudflare scores partly on IP reputation. This is one network on one day, and AIC
almost certainly does not intend it — the `AIC-User-Agent` bypass exists so API clients work, and
images are collateral. It may not reproduce everywhere, and it may change.

Because of that caveat the frontend **tries the direct AIC URL first and falls back to the
proxy** on failure, rather than proxying unconditionally. See ADR-0008.

---

## Licensing and attribution

- The `description` field is licensed CC BY 4.0 — it requires attribution.
- All other data is CC0 1.0. Both statements are returned in the `info.license_text` of every
  response.
- Terms: <https://www.artic.edu/terms>. Image licensing: <https://www.artic.edu/image-licensing>.
- AIC's IIIF manifests carry "Digital image courtesy of the Art Institute of Chicago." Something
  equivalent belongs in the metadata overlay.
- We enforce public domain as a hard filter, which also sidesteps per-work image rights.

---

## Error handling

Retry with backoff: connection errors, timeouts, `429`, `5xx`.
Do not retry: `400`, `403`, `404`, or any malformed-query response — those are our bugs.
Note that a Cloudflare challenge also arrives as `403`, and retrying it is equally pointless.

Every response must go through a Pydantic model. AIC returns `null` rather than empty strings,
and empty arrays rather than `null` for list fields, so model those as `Optional[str]` and
`list[T] = []` respectively. Missing `image_id` is common — 55% of records — and means
"skip this artwork".
