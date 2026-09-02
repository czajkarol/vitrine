# Art Institute of Chicago API

Everything here was read off the official docs at <https://api.artic.edu/docs/> and is
marked **confirmed** or **unverified**. Do not build on anything marked unverified without
checking a live response first — and when you do check, move it up and say so.

Base URL: `https://api.artic.edu/api/v1`

---

## Limits and etiquette (confirmed)

| Constraint | Value                                                                                   |
|---|-----------------------------------------------------------------------------------------|
| Authentication | None. Public API, no key.                                                               |
| Throttle | 60 requests/minute per IP for anonymous users                                           |
| `limit` per page | Max 100, default 12                                                                     |
| Deep pagination | Search endpoints refuse anything past 10,000 records via any `limit`/`page` combination |
| Courtesy header | `AIC-User-Agent: vitrine (karolkczaj@gmail.com)` on every request                       |
| Scraping | Single thread, no more than 1 request/second, no parallel scrapers                      |
| Bulk data | Nightly JSON data dumps at <https://github.com/art-institute-of-chicago/api-data>       |

AIC's own guidance is to use the data dumps rather than scrape the API when you want more
than 10,000 records, and to cache responses locally. Both apply directly to us — see ADR-0003.

`limit=0` returns only the `pagination` block, which makes it a cheap way to count matches
for a filter without transferring any records.

---

## Endpoints we use

```
GET /artworks/search        Elasticsearch-backed. q, query (ES DSL), sort, from, size, facets
GET /artworks?ids=1,2,3     Batch detail fetch — preferred over N single requests
GET /artworks/{id}          Single artwork
GET /artwork-types          ~45 types. "Painting" is id 1. Use to build Explore filters.
GET /category-terms         Style / subject / department vocabulary, with a `subtype` field
```

Always pass `fields=` to limit the payload. AIC asks for this explicitly and it makes
responses meaningfully smaller.

Public-domain filter, confirmed working:

```
/artworks/search?query[term][is_public_domain]=true&limit=0
```

For production, AIC recommends `GET` with the whole query as minified URL-encoded JSON in
a `params` parameter rather than deeply nested bracket syntax. `POST` is for complex payloads.

---

## Fields

### Confirmed present in `/artworks/search` responses

| Field | Why it matters |
|---|---|
| `id`, `title`, `api_link` | Identity |
| `is_boosted` | AIC boosts its own "essentials" group in search. A free, honest curatorial signal — use it in Curated scoring rather than inventing one. |
| `thumbnail.lqip` | Base64 GIF blur placeholder, inline in the response. Paint it instantly, fade the real image in over it. Costs one extra network request: zero. |
| `thumbnail.alt_text` | Human-written visual description from the museum. Use for `alt=`, and as grounding context in AI prompts so the model describes the actual picture. |
| `thumbnail.width` / `height` | Real source dimensions (often thousands of px). Use for quality filtering and aspect-ratio scoring. |
| `_score`, `timestamp` | Relevance and last-update |

### Confirmed present in listing/detail responses

`image_id`, `alt_image_ids`, `artist_display`, `artist_title`, `date_display`,
`main_reference_number`, `classification_titles`, `style_ids`, `term_titles`,
`is_public_domain`, `description`.

### Unverified — check before use

- `color` — a dominant-colour object. Widely referenced, not confirmed in the docs excerpt read
  here. If it exists and carries HSL plus a population count, use it to tint the page background
  behind the artwork. If it does not, derive an average colour from `thumbnail.lqip` instead,
  which is guaranteed to be there.
- `date_start` / `date_end` as integers.
- `is_on_view`, `department_title`, `place_of_origin`, `medium_display`, `subject_titles`.
- `style_titles` — `style_ids` is confirmed; the `_titles` twin is likely but unconfirmed.

Confirming one of these is a two-minute job: fetch `/artworks/27992` and read the response.
Do that before designing a filter around it, and update this table.

---

## Images (IIIF)

The API contains no image files. Images come from a separate IIIF Image API 2.0 service.

```
{config.iiif_url}/{image_id}/full/{width},/0/default.jpg
```

- `config.iiif_url` is returned on every API response. **Read it, never hardcode it.**
- Cached widths: `200`, `400`, `600`, `843`. Also `1686` for public-domain works.
- **Prefer `843`.** AIC's own site uses it, so it is the size most likely to already be cached
  at their edge. Using an odd width means a cache miss and a slow first paint.
- The number 843 comes from museum-sector guidelines on the use of copyrighted material.
- Images are served with `Access-Control-Allow-Origin: *` and AIC states it does not mind
  hotlinking. Load them directly in the browser. **Do not build an image proxy.**
- Any image may be unpublished or replaced without notice. The frontend must survive an image
  404 by skipping to the next artwork rather than showing a broken frame.

Width selection: pick from the cached ladder based on `window.innerWidth * devicePixelRatio`,
capped at 1686. Do not request arbitrary widths.

---

## Licensing and attribution

- The `description` field is licensed CC BY 4.0 — it requires attribution.
- All other data is CC0 1.0.
- Terms: <https://www.artic.edu/terms>. Image licensing: <https://www.artic.edu/image-licensing>.
- AIC's own IIIF manifests carry the attribution string "Digital image courtesy of the Art
  Institute of Chicago." Something equivalent belongs in the metadata overlay.
- AIC recommends using only artworks tagged public domain. We enforce that as a hard filter,
  which also sidesteps the question of per-work image rights entirely.

---

## Error handling

Retry with backoff: connection errors, timeouts, `429`, `5xx`.
Do not retry: `400`, `403`, `404`, or any malformed-query response — those are our bugs.

Every response must go through a Pydantic model. AIC returns `null` rather than empty strings,
and empty arrays rather than `null` for list fields, so model those as `Optional[str]` and
`list[T] = []` respectively. Missing `image_id` is common and means "skip this artwork".
