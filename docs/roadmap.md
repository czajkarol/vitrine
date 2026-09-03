# Roadmap

Work top to bottom. Tick items off as they land. Keep this file honest — it is the shared view
of where the project is.

The ordering is deliberate: a thin vertical slice first, then depth. Do not build the AI provider
abstraction before there is a picture on the screen.

---

## M0 — Vertical slice

The goal is one real artwork on screen, fetched over the network, in a browser. Nothing else.

- [x] `pyproject.toml`, dependencies installed, `ruff` + `mypy` + `pytest` running clean
- [x] `.gitignore`, `.env.example`, `data/` ignored, first commit
- [x] Settings object loaded from environment via `pydantic-settings`
- [x] `AicClient` with the `AIC-User-Agent` header, timeout, and a 60 req/min throttle
- [x] `Artwork` domain model + parsing from one real AIC response
- [x] Contract test against a recorded response fixture (`respx`)
- [x] One `-m live` test that hits the real API, excluded from the default run
- [x] `GET /api/artwork/random` returning one public-domain artwork
- [x] `index.html` that displays it full-bleed on a dark background
- [x] Commit

## M1 — The display

- [x] Transition pipeline: `lqip` → `new Image()` → `decode()` → crossfade
- [x] Image 404 and decode failure skip to the next artwork
- [x] IIIF width selection from viewport and `devicePixelRatio`, clamped to the cached ladder
- [x] Rotation timer with 1/5/15/30 intervals, default 5
- [x] Next-artwork preload scheduled ahead of expiry
- [x] `visibilitychange` catch-up so a backgrounded tab does not drift
- [x] Keyboard shortcuts per `docs/product-spec.md`, disabled inside inputs — the whole map,
      `S` included once M3 gave it a settings panel to open
- [x] Fullscreen via the Fullscreen API — verified by hand on 2026-09-03. It needs a real
      user gesture, which browser automation cannot supply, so it took a human keypress
- [x] Metadata overlay with mouse-idle fade, AIC attribution included
- [x] `prefers-reduced-motion` cuts instead of fading
- [x] Commit

## M2 — Local index and persistence

This is the milestone that makes the rest possible. See ADR-0003.

- [x] SQLite setup, WAL mode, migration runner
- [x] `artwork_index` schema and repository
- [x] `scripts/build_index.py` — resumable, idempotent, 1 req/s, `--limit` flag
- [x] Public-domain and image-quality filtering at index time
- [x] Random sampling from the index, with the history penalty
- [x] `history` table, last ~50 IDs
- [x] Preferences persistence — interval, mode and artwork type survive a reload; M4 adds language
- [x] Bundled fallback set of ~30 artworks for the no-network case — metadata only, so it
      covers "the API is down", not "no internet at all"
- [x] Commit

## M3 — Modes

- [x] Scoring module in `domain/`, pure, one weights dict with a comment per weight
- [x] Unit tests for scoring, including a ranking-order test
- [x] `--explain` flag printing a score breakdown
- [x] Curated mode wired to the index — curated ranks, it does not exclude: with nothing
      scored yet it serves unranked rather than showing a blank screen
- [x] Filter vocabulary built from `/artwork-types` at index time, with real counts —
      style and subject moved to their own step below, see `QUESTIONS.md` #10
- [x] Explore mode UI, showing match counts, hiding filters with too few results
- [x] Commit

## M3.5 — Style and subject filters

Split out of M3 deliberately. `style_titles` and `subject_titles` are confirmed present on AIC
responses (`docs/aic-api.md`) but are not in the index, and adding them means re-walking the
collection.

The schema and crawl changes went first, then **one** walk covering everything outstanding.
Per `CLAUDE.md` that walk needed the owner's approval before it started, and it got it —
see the last item below. Nothing here is outstanding.

- [x] Add `style_titles` and `subject_titles` to `ARTWORK_FIELDS` and the `artwork_index` schema
- [x] Decide how a multi-valued filter is stored — a join table, `artwork_terms`. Reasoning in
      migration 007: Explore asks "how many artworks have subject X" for every X on every panel
      open, and JSON in a column cannot answer that without a full scan of the index
- [x] Extend `/api/filters` and the Explore panel to offer style and subject alongside type —
      capped at the 30 most populous values, because these vocabularies run to thousands where
      artwork type is a closed list of 45
- [x] One re-walk covering this and anything else pending, with approval — the owner approved it
      on 2026-09-03. All 1,328 pages, 132,741 records, 57,607 indexed, 84,190 term rows, in
      30 minutes. 92 styles and 216 subjects clear the 40-artwork bar, which is why the
      30-option cap exists
- [x] Commit

## M4 — Settings and i18n

- [x] Settings panel, pauses rotation while open — built in M3 to give Explore somewhere
      to live and to bind `S`. M4 adds language, ambient mode and the AI toggles to it
- [x] `i18n.js` + `en.json` + `pl.json`, every string keyed including errors — the panel's
      own labels are keyed in markup with `data-i18n`, and `language` joins the preferences
- [x] Language switch without reload — radios in the panel; the caption, the filter list
      and any status message on screen are retranslated in place
- [x] Ambient mode via Screen Wake Lock, re-acquired on `visibilitychange` — off by default,
      and the toggle is removed outright where the API is missing
- [x] Commit

## M5 — AI

- [x] `Interpretation` model and JSON-only prompt — instruction and data kept apart,
      grounded in `thumbnail.alt_text`
- [x] `InterpretationProvider` protocol + `MockProvider`
- [x] Full feature wired end to end against the mock — `GET /api/interpretation/{id}`,
      its own labelled section in the overlay, and `/api/health` says whether to offer it
- [x] SQLite interpretation cache with the composite key — validated on the way out, so a
      row from an older shape is a miss rather than something the display trusts
- [x] `NullSharedCache` and the three-tier resolution chain — a cache that raises is
      skipped, never propagated
- [x] Budget guard: token cap, daily request cap, `ai_usage` tracking — checked before the
      call, and a cache hit is never counted against it
- [x] Circuit breaker with cooling period — a failed trial call after the cooldown
      reopens immediately, and an open circuit still serves the cache
- [x] Generation on demand only — never on rotation. Tied to pinning the overlay with `I`,
      not to the overlay's own flash on every artwork change
- [x] One real provider — Anthropic, the owner's choice. Live tests are `-m live` and skip
      themselves without a key
- [x] A second real provider, to prove the abstraction — OpenAI. `base.py` did not have
      to change; the shared HTTP plumbing moved to `providers/ai/http.py`
- [x] BYO key handling with keyring preference and redaction everywhere — the keyring is
      probed rather than imported, because an installed `keyring` with no working backend
      raises only when used; the SQLite fallback says so in the panel before anything is
      typed. A saved key outranks `.env` and swaps the provider without a restart
- [x] Commit

## M6 — Finish

- [x] `/api/stats` (cache hit ratio, provider latency, AIC error rate) — `GET /api/health` is done.
      Counters live in `domain/metrics.py`, in memory and from process start; the only figure
      that survives a restart is today's AI spend, which is the only one anything enforces
      against. Nothing in the frontend reads it
- [x] Structured logging, no secrets, request IDs — `LOG_FORMAT=text|json`, one id per
      request from a `ContextVar` so existing log calls did not have to change, honoured
      from an inbound header, and a redaction pass over every record that catches a
      key-shaped token whatever wrote it
- [x] Playwright smoke tests: loads, advances, overlay opens, language switches, AI-disabled
      state — the fixture starts its own uvicorn against a temporary database seeded from the
      bundled set, so `uv run pytest -m e2e` needs nothing set up but Chromium
- [x] GitHub Actions: ruff, mypy, pytest excluding live and e2e
- [x] README written properly — architecture, setup, AI, caching, testing, security, limitations
- [x] Screenshots — `docs/screenshots/`, the display and the settings panel
- [x] ADRs reviewed against what was actually built — four gained a postscript, none had to
      be superseded. The one that mattered: 0003 claimed AIC is called to refresh the artwork
      about to be shown, and no such call exists
- [x] Commit

---

## M7 — Truth-up

Documentation and naming only, with the one exception noted below. Details in
`docs/plan-improvements.md` Phase 0. Do this first: every later milestone edits these files.

- [x] Replace the personal name with "the owner" in `CLAUDE.md`, `HANDOFF.md`, `QUESTIONS.md`
      and this file — `HANDOFF.md` had none left
- [x] Placeholder contact address in `app/core/config.py`, `tests/conftest.py`,
      `docs/aic-api.md`, plus a startup warning when it is still the default — the one
      behaviour change in M7, and the reason it is worth it: with no `.env` the app now sends
      a header AIC would consider unhelpful, so it has to say so somewhere a person will look
- [x] Reconcile `README.md` (style/subject *are* built), `HANDOFF.md` (it contradicts itself
      about M3.5), `docs/architecture.md` (`classification` was renamed; `artwork_terms` and
      `credentials` are missing) and the test count both files quote — 349, not 334, and
      `HANDOFF.md` had already been rewritten
- [x] Drop the unused `ai` extra from `pyproject.toml` and the orphan keys from `.env.example`
- [x] Amend `QUESTIONS.md` #2 (`S` stays bound and now toggles) and #3 (the description
      clamp gains an expand affordance) with dated notes rather than silent contradiction —
      and a status note on #10, whose ruling stands but whose opening sentence had gone stale
- [x] Commit

## M8 — The display

- [x] Scrim strength driven by the artwork's own `color.l`, plus a text shadow and a readable
      `--fg-dim` — verified in a browser against a white-ground print and a dark painting.
      The check changed the design: AIC's `color` is the dominant colour of the whole image,
      and a Homer watercolour on tan paper reports `l = 6` while reading as a bright ground
      under the caption. So the *default* scrim is now strong enough alone (0.88 / 0.66 / 55%)
      and `l > 60` only adds to it. A hint, never the mechanism
- [x] Serif for museum text, self-hosted `woff2`, system sans kept for the interface —
      EB Garamond, OFL 1.1, with `frontend/fonts/OFL.txt` as the licence requires. Two
      variable files, `latin` and `latin-ext`, 155KB; `latin-ext` is what keeps Polish
      diacritics in the same face on the attribution line. The AI section takes the sans
      back, which is the strongest version of "never mistakable for a museum caption"
- [x] Expandable description behind a small `i` button, collapsing on rotation and on Esc —
      shown only when the clamp is actually hiding something, measured from `scrollHeight`.
      While it is open the idle fade stretches from 3.5s to 20s: reading is not moving the
      mouse, and 3.5s takes the text away mid-paragraph
- [x] `S` toggles the settings panel, so it can be closed while fullscreen without Esc
      dropping out of fullscreen
- [x] A manual "next artwork" control inside the overlay, sharing one 1500ms cooldown with Space
- [x] **Not planned, found by the browser check:** `chooseWidth()` asked for 1686 on a wide
      monitor whatever the artwork's own size. AIC's IIIF service answers `403` rather than
      upscaling, and the display treats that as an unloadable image and skips — so **8,993 of
      the 57,607 indexed works, one in six, could not be shown at all**. Now clamped to
      `thumbnail.width`, which was already on every response
- [x] Commit

## M9 — Rate limiting

- [ ] `domain/rate_limit.py`: a pure token bucket, the clock passed in
- [ ] Applied to `/api/artwork/random` and `/api/image/{image_id}`; 429 with `Retry-After`
- [ ] The frontend waits out `Retry-After` calmly and never retry-storms
- [ ] Commit

## M10 — Canonical facets

The largest milestone, and it needs **no AIC traffic**: the raw terms are already in SQLite.

- [ ] `domain/vocabulary.py` — the canonical facet map, pure, with every dropped value listed
      and commented
- [ ] Migration 008 `artwork_facets`, with artwork type folded in as `type.*` so all three
      groups share one query shape
- [ ] `build_index.py --retag`, and run automatically after a crawl
- [ ] Exclusion: multi-valued per group, `NOT IN`, offered as a sub-list under each group
- [ ] Dependent counts between the groups, leave-one-out, zero-count options disabled not hidden
- [ ] Facet labels in `locales/`, Polish written as UI copy rather than as translation
- [ ] ADR-0009 — canonical facets over AIC's raw terms
- [ ] Commit

## M11 — Modes, scoring explained, favourites

- [ ] Mode options rendered as name + quiet description; the em dashes leave the strings
- [ ] `GET /api/scoring` and an `i` beside Mode explaining the weights in both languages,
      with the numbers taken from the code
- [ ] Migration 009 `artwork_feedback` — no foreign key, with a small snapshot
- [ ] `L` likes, `X` hides, a heart in the overlay, `GET`/`PUT`/`DELETE /api/favorites`
- [ ] "For you" as a third mode over `domain/affinity.py`, falling back to Curated below
      about five likes and saying so
- [ ] ADR-0010 — personalisation from explicit feedback only
- [ ] Commit

## M12 — Data, setup, and other sources

- [ ] `scripts/export_index.py` — corpus tables only, into a fresh file, `VACUUM`ed
- [ ] `scripts/fetch_index.py` — merge a published export without touching preferences,
      history or credentials
- [ ] `docs/setup.md`, verified by following it on a clean checkout
- [ ] `docs/data.md` — what is stored, what is rebuildable, what may be published and why the
      database is not committed
- [ ] ADR-0011 — distribute the index as a release asset, never in Git
- [ ] ADR-0012 (Proposed) — additional art sources, and what a second one would actually cost
- [ ] ADRs re-read against the code, `docs/architecture.md` and `HANDOFF.md` reconciled
- [ ] Commit

---

## Not doing

Recorded here so it does not get relitigated. Each has an ADR or a line in `CLAUDE.md`.

- Shared/public interpretation cache — interface only (ADR-0004)
- Machine learning for curation — transparent weights instead
- ~~Image proxying~~ — reversed by ADR-0008. Cloudflare blocks hotlinking of AIC's IIIF
  images, so `GET /api/image/{image_id}` exists as a fallback after a direct load fails.
- OS-level power management — Screen Wake Lock covers it
- Frontend framework or build step
- Docker, Alembic, Redis, a DI framework
