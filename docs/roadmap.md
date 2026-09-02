# Roadmap

Work top to bottom. Tick items off as they land. Keep this file honest — it is the shared view
of where the project is.

The ordering is deliberate: a thin vertical slice first, then depth. Do not build the AI provider
abstraction before there is a picture on the screen.

---

## M0 — Vertical slice

The goal is one real artwork on screen, fetched over the network, in a browser. Nothing else.

- [ ] `pyproject.toml`, dependencies installed, `ruff` + `mypy` + `pytest` running clean
- [ ] `.gitignore`, `.env.example`, `data/` ignored, first commit
- [ ] Settings object loaded from environment via `pydantic-settings`
- [ ] `AicClient` with the `AIC-User-Agent` header, timeout, and a 60 req/min throttle
- [ ] `Artwork` domain model + parsing from one real AIC response
- [ ] Contract test against a recorded response fixture (`respx`)
- [ ] One `-m live` test that hits the real API, excluded from the default run
- [ ] `GET /api/artwork/random` returning one public-domain artwork
- [ ] `index.html` that displays it full-bleed on a dark background
- [ ] Commit

## M1 — The display

- [ ] Transition pipeline: `lqip` → `new Image()` → `decode()` → crossfade
- [ ] Image 404 and decode failure skip to the next artwork
- [ ] IIIF width selection from viewport and `devicePixelRatio`, clamped to the cached ladder
- [ ] Rotation timer with 1/5/15/30 intervals, default 5
- [ ] Next-artwork preload scheduled ahead of expiry
- [ ] `visibilitychange` catch-up so a backgrounded tab does not drift
- [ ] Keyboard shortcuts per `docs/product-spec.md`, disabled inside inputs
- [ ] Fullscreen via the Fullscreen API
- [ ] Metadata overlay with mouse-idle fade, AIC attribution included
- [ ] `prefers-reduced-motion` cuts instead of fading
- [ ] Commit

## M2 — Local index and persistence

This is the milestone that makes the rest possible. See ADR-0003.

- [ ] SQLite setup, WAL mode, migration runner
- [ ] `artwork_index` schema and repository
- [ ] `scripts/build_index.py` — resumable, idempotent, 1 req/s, `--limit` flag
- [ ] Public-domain and image-quality filtering at index time
- [ ] Random sampling from the index, with the history penalty
- [ ] `history` table, last ~50 IDs
- [ ] Preferences persistence
- [ ] Bundled fallback set of ~30 artworks for the no-network case
- [ ] Commit

## M3 — Modes

- [ ] Scoring module in `domain/`, pure, one weights dict with a comment per weight
- [ ] Unit tests for scoring, including a ranking-order test
- [ ] `--explain` flag printing a score breakdown
- [ ] Curated mode wired to the index
- [ ] Filter vocabulary built from `/artwork-types` and `/category-terms` at index time
- [ ] Explore mode UI, showing match counts, hiding filters with too few results
- [ ] Commit

## M4 — Settings and i18n

- [ ] Settings panel, pauses rotation while open
- [ ] `i18n.js` + `en.json` + `pl.json`, every string keyed including errors
- [ ] Language switch without reload
- [ ] Ambient mode via Screen Wake Lock, re-acquired on `visibilitychange`
- [ ] Commit

## M5 — AI

- [ ] `Interpretation` model and JSON-only prompt
- [ ] `InterpretationProvider` protocol + `MockProvider`
- [ ] Full feature wired end to end against the mock
- [ ] SQLite interpretation cache with the composite key
- [ ] `NullSharedCache` and the three-tier resolution chain
- [ ] Budget guard: token cap, daily request cap, `ai_usage` tracking
- [ ] Circuit breaker with cooling period
- [ ] Generation on demand only — never on rotation
- [ ] One real provider
- [ ] A second real provider, to prove the abstraction
- [ ] BYO key handling with keyring preference and redaction everywhere
- [ ] Commit

## M6 — Finish

- [ ] `GET /api/health` and `/api/stats` (cache hit ratio, provider latency, AIC error rate)
- [ ] Structured logging, no secrets, request IDs
- [ ] Playwright smoke tests: loads, advances, overlay opens, language switches, AI-disabled state
- [ ] GitHub Actions: ruff, mypy, pytest excluding live and e2e
- [ ] README written properly — architecture, setup, AI, caching, testing, security, limitations
- [ ] Screenshots
- [ ] ADRs reviewed against what was actually built
- [ ] Commit

---

## Not doing

Recorded here so it does not get relitigated. Each has an ADR or a line in `CLAUDE.md`.

- Shared/public interpretation cache — interface only (ADR-0004)
- Machine learning for curation — transparent weights instead
- Image proxying — AIC permits hotlinking and serves permissive CORS
- OS-level power management — Screen Wake Lock covers it
- Frontend framework or build step
- Docker, Alembic, Redis, a DI framework
