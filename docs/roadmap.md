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

Do the schema and crawl changes first, then run **one** walk covering everything outstanding.
Per `CLAUDE.md`, ask Karol before starting it.

- [ ] Add `style_titles` and `subject_titles` to `ARTWORK_FIELDS` and the `artwork_index` schema
- [ ] Decide how a multi-valued filter is stored — a join table, or JSON in a column
- [ ] Extend `/api/filters` and the Explore panel to offer style and subject alongside type
- [ ] One re-walk covering this and anything else pending, with approval
- [ ] Commit

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
- [x] One real provider — Anthropic, Karol's choice. Live tests are `-m live` and skip
      themselves without a key
- [x] A second real provider, to prove the abstraction — OpenAI. `base.py` did not have
      to change; the shared HTTP plumbing moved to `providers/ai/http.py`
- [ ] BYO key handling with keyring preference and redaction everywhere
- [ ] Commit

## M6 — Finish

- [ ] `/api/stats` (cache hit ratio, provider latency, AIC error rate) — `GET /api/health` is done
- [ ] Structured logging, no secrets, request IDs
- [ ] Playwright smoke tests: loads, advances, overlay opens, language switches, AI-disabled state
- [x] GitHub Actions: ruff, mypy, pytest excluding live and e2e
- [ ] README written properly — architecture, setup, AI, caching, testing, security, limitations
- [ ] Screenshots
- [ ] ADRs reviewed against what was actually built
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
