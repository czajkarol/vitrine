# Handoff

State of vitrine as of 2026-09-03. `CLAUDE.md` is the contract; this file is what you cannot
derive from it. Read `docs/plan-improvements.md` next — it is the agreed work.

---

## Where the project is

**M0 through M6 are complete, M3.5 included.** The roadmap is ticked against the code, not
against intentions.

The app works end to end. It serves an artwork from a local SQLite index in ~19ms with **no AIC
call at all**, rotates on a timer, has a keyboard map, a metadata overlay set in a serif, a settings panel with
Explore filters over artwork type, style and subject, and a Curated mode backed by transparent
scoring. English and Polish, switchable without a reload. Ambient mode holds a Screen Wake Lock.

AI is wired end to end and off by default. Pinning the overlay with `I` asks for an
interpretation; it is cached, capped and breakered. Anthropic and OpenAI are both built behind
one interface, and a key pasted into the settings panel takes effect without a restart. With
nothing configured the feature is simply not offered — that is a `CLAUDE.md` non-negotiable and
is worth re-checking after any change near it.

The index holds **57,607 artworks**, all scored, plus 84,190 style/subject rows.
`data/vitrine.db` is 60MB and gitignored.

**M7, M8 and M9 are done. M10–M12 are queued.** See `docs/roadmap.md` for the list and
`docs/plan-improvements.md` for the design and the decisions. Of the six that needed a ruling,
three were taken at the top of M8 (font, rate-limit numbers, how far to fold the facet
vocabulary), two were proceeded on under a stated assumption and are one substitution to
reverse, and one — "more like this" — stays a proposal that is deliberately not in the roadmap.

M8 and M9 each changed more than their own list. Three bugs that a passing suite could not see
turned up as soon as the app was opened and looked at, and all three are in the Gotchas below:
AIC refusing to upscale made one indexed artwork in six unshowable; `color.l` turned out to be
a hint about the whole image rather than a fact about the bottom of it; and the new rate
limiter, on its first run in a browser, caused exactly the retry storm it was written to
prevent.

## Run it

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
uv run pytest                             # unit + contract; excludes live and e2e
uv run pytest -m live                     # the real AIC API, and the AI providers if keyed
uv run pytest -m e2e                      # six Playwright flows; needs `playwright install chromium`
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

```bash
uv run python scripts/build_index.py             # full walk: 1,328 requests, ~30 min, resumable
uv run python scripts/build_index.py --limit 5000
uv run python scripts/build_index.py --score-only
uv run python scripts/build_index.py --explain <artwork_id>
```

A fresh clone has no index and serves from AIC, then from the bundled 30-record fallback set.
`AI_ENABLED=true AI_PROVIDER=mock` runs the AI path with no key and no network.

## Constraints that must not be relitigated

- **Ask before sustained external traffic.** Several minutes, or a substantial number of
  requests, even inside AIC's documented limits. A full `build_index.py` walk needs approval; a
  handful of calls to check a field does not. `CLAUDE.md`, `QUESTIONS.md` #8.
- **Public domain only**, enforced at index time and at display time. ADR-0007.
- **No frontend framework, no build step.** ADR-0005.
- **`domain/` imports nothing outward**, only `providers/aic/` knows AIC's JSON shape, only
  `providers/ai/` names a vendor, config is injected. `ruff` enforces the `httpx` half of this.
  `docs/architecture.md`.
- **AI is an enhancement, never a dependency.** No key configured must mean the feature is not
  offered, not that anything fails.
- **Never hardcode the IIIF base**; it arrives on every AIC response and is remembered in
  `preferences`.
- **Scoring weights are product heuristics, not claims about art.** Keep them tunable; tests
  assert ordering, never values. ADR-0006, `QUESTIONS.md` #11.
- **The index is a cache, not truth.** AIC can unpublish an image at any time. ADR-0003.
- `QUESTIONS.md` is a settled record of twelve rulings, not an open list. Read it before
  changing anything it covers. Two were reopened deliberately in M7 — #2 (`S` toggles) and #3
  (the description gains an expand affordance) — and both carry a dated amendment in place. That
  is how a ruling changes here. Contradicting one in the code and leaving this file saying the
  opposite is not.

## Gotchas

All found the hard way, in a browser or against the live API. Each is documented where named.

1. **`img.decode()` never settles in a hidden tab** — pending forever, while `load` fires
   normally. `display.js` races the two. Same family: **`requestAnimationFrame` does not run in
   a hidden tab**, so nothing a user must see may depend on an rAF callback; and **a Screen Wake
   Lock is released when the tab hides and is not given back**, so `ambient.js` re-acquires on
   `visibilitychange`. `docs/product-spec.md`.
2. **Cloudflare blocks IIIF hotlinking and does not always reject cleanly** — sometimes the
   request simply never answers, so every image load needs a deadline. ADR-0008.
3. **`classification_title` is not the artwork type** — on a Seurat it reads "oil on canvas".
   Filter on `artwork_type_title`. `docs/aic-api.md`.
4. **`/artworks/search` caps at 1,000 records; `/artworks` is uncapped.** That difference is the
   whole reason the local index works. ADR-0003's postscript.
5. **AIC returns `title: null`**, first seen at record ~112,000. The parser skips and logs
   records it cannot validate rather than aborting. A handful of skips is data; a page of them
   is a contract break. `AicClient._parse_records`.
6. **Tests must set `database_path`** — the `settings` fixture in `tests/conftest.py` points at a
   tmp file. Without it the suite reads and writes the real index.
7. **Chrome caches ES modules hard**, and a stale one fails as a blank screen with
   "does not provide an export named X" for an export that is plainly there. Refetch each changed
   file with `fetch(url, { cache: 'reload' })`, then reload. There is no build step and no
   cache-busting, so this keeps happening.
8. **FastAPI's 422 echoes the rejected input**, which for the API key field meant the key came
   back out in the error body. `app/api/errors.py` strips `input` and `ctx`. `SecretStr` does not
   help — pydantic reports what it was handed, before the field type applies.
9. **AIC's IIIF service will not upscale, and a `403` looks exactly like a dead image.**
   Requesting `full/1686,` from a source 1602px wide is a `403`, which `display.js` treats as
   an artwork whose image will not load, and skips. One in six indexed works is narrower than
   1686. `chooseWidth()` now clamps to `thumbnail.width`. `docs/product-spec.md`.
10. **`color.l` does not tell you how bright the bottom of the picture is.** AIC reports the
    dominant colour of the whole image. A graphite-on-tan-paper Homer comes back at `l = 6`,
    as dark as anything in the collection, and reads as cream under the caption. The overlay
    scrim uses it, but only to *add* to a default that is already legible.
11. **An `<img>` cannot see an HTTP status, so a `429` on the image proxy looks exactly
    like a dead image.** The display's response to a dead image is to skip to another
    artwork immediately, which spends more of the budget that just refused it — the
    limiter causing the storm it exists to prevent. The unit limited is therefore an
    *advance*: an allowed artwork request grants a credit its image spends.
    `app/domain/rate_limit.py`.
12. **There is no way to unit-test the frontend here, and that is deliberate.** No bundler, no
    `node_modules`, so no test runner (ADR-0005). Playwright covers five smoke flows and no
    more. The bugs above were invisible to a passing suite and were found by opening the app
    and looking at it, which is why the definition of done says to.
13. **`.gitignore` patterns without a leading slash match at any depth.** A bare `data/`
    silently excluded `app/data/fallback_artworks.json`, the bundled offline set.
    `QUESTIONS.md` #9.
14. **`data/vitrine.db` holds a secret.** When there is no OS keyring, a pasted API key sits
    unencrypted in the same file as the index. Never commit, publish or attach it.
    `docs/plan-improvements.md` Phase 6.

## Outstanding, and only the owner can close it

**`uv run pytest -m live` with a real key.** Neither provider has ever been called with a working
key. It is the only thing that can catch a wrong default model id, or `max_completion_tokens`
being wrong for the model in use. A fake key was pushed through the whole path in a browser and
came back a clean 401 — which proves the wiring and nothing about the model ids.

## Conventions worth matching

- `CLAUDE.md` is the contract; `app/`, `frontend/` and `tests/` each have their own.
- Fix the doc in the same commit as the code when reality disagrees with it.
- Commit messages say *why*, and name what was found rather than just what changed.
- Fixtures are recorded real responses in `tests/fixtures/aic/`, never hand-written.
- Definition of done includes opening it in a browser and looking at it. Every rendering bug in
  the list above was invisible to a passing test suite.
