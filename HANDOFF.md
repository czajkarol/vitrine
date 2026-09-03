# Handoff

State of vitrine as of 2026-09-03. Written for whoever (or whatever) picks this up next.

---

## Where the project actually is

M0 through M4 are complete and committed, apart from one scoped-down item in M3 (M3.5, parked
deliberately — see below). `docs/roadmap.md` is accurate: it was reconciled against the code,
not against intentions, and is ticked as work lands.

The app works end to end: it serves an artwork from a local SQLite index in ~19ms with no
network call, rotates on a timer, has a keyboard map, a metadata overlay, a settings panel with
Explore filters, and Curated mode backed by transparent scoring. It speaks English and Polish,
switchable without a reload, and will hold the screen awake if asked.

No AI anywhere yet. That is M5, and `CLAUDE.md` is emphatic that it stays an enhancement: the
app has to remain fully usable with nothing configured.

## Run it

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
uv run pytest                             # 155 tests, excludes live/e2e
uv run pytest -m live                     # 6 tests, hits the real AIC API
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

`data/vitrine.db` is gitignored, so a fresh clone starts with no index and serves from AIC,
then from the bundled fallback set. To build the index:

```bash
uv run python scripts/build_index.py             # full walk, ~22 min at 1 req/s, resumable
uv run python scripts/build_index.py --limit 5000
uv run python scripts/build_index.py --score-only
uv run python scripts/build_index.py --explain <artwork_id>
```

## What to do next

**M5 — AI** is the next milestone. Build it against `MockProvider` first and get the whole
feature working end to end before a real vendor appears; `docs/ai-system.md` has the cache key,
the budget guard and the circuit breaker. Two things in `CLAUDE.md` bound it: no provider key
ever reaches the frontend, and the app stays fully usable with nothing configured. The overlay
already has a comment marking where interpretation goes, and why it must not share a container
with the museum facts.

Note that **M3.5 sits above M4 in the roadmap and is deliberately parked**: style and subject
filters need a full re-crawl, and Karol ruled they wait to be batched with other indexing work
rather than triggering a 22-minute walk on their own. Do not start there just because it comes
first in the file.

What M4 put in place, and what M5 extends:

- **Strings.** `frontend/locales/en.json` and `pl.json`, loaded by `frontend/js/i18n.js`.
  `t('key', { placeholder })` for text built in JS; `data-i18n="key"` in markup, which
  `applyTo()` fills in. A new string means a key in *both* files — they are checked against
  each other by eye, so keep them in the same order.
- **Number-shaped strings.** Polish inflects a counted noun three ways and there is no plural
  machinery. Phrase around it (`Dzieł w indeksie: {total}.`), do not add a plural library.
  Numbers substituted into a template are formatted for the active locale automatically.
- **Live retranslation.** `onLanguageChange()` in `i18n.js` notifies; `retranslate()` in
  `main.js` redraws the caption, the filter list and any status message currently on screen.
  Anything new that renders text from data has to be added there — markup with a key does not.
- **Preferences.** `GET`/`PUT /api/preferences`, a typed schema in `app/api/schemas.py`.
  A new preference means a field there and a key constant in `app/api/routes.py`. Interval,
  mode, artwork type, language and ambient are wired; the AI toggles are next. The table
  stores strings, so a boolean is written `"1"`/`"0"` and only `"1"` reads back as true.
- **The panel** (`frontend/js/panel.js`) opens on `S`, closes on `Esc`, and pauses rotation
  while open. It holds mode, Explore filters, ambient and language. The AI toggles join it.
  A control the browser cannot support is removed rather than disabled — see `hideAmbient()`.
- **Language is part of the AI cache key** (`docs/product-spec.md`, `docs/architecture.md`).
  `getLanguage()` from `i18n.js` is the frontend's source of truth for it; the backend's is
  the `language` preference.

## Things that will bite you if you do not know them

These were all found the hard way, in a browser or against the live API. Each is documented in
the file named, but they are the ones that cost real time.

1. **`img.decode()` never settles in a hidden tab.** Not resolved, not rejected — pending
   forever. The `load` event fires normally. An ambient display is hidden much of its life, so
   `decode()` alone strands the rotation on "Loading…". `frontend/js/display.js` races the two.
2. **`requestAnimationFrame` does not run in a hidden tab either.** Never make anything a user
   must see depend on an rAF callback. This cost an artwork stuck at opacity 0.
3. **Cloudflare blocks IIIF hotlinking, and does not always reject cleanly** — sometimes the
   request just never answers. Every image load needs a deadline. See ADR-0008.
4. **AIC returns `title: null`.** Found at record ~112,000 of a full walk; a partial crawl of
   2,000 looked perfectly healthy. The parser now skips records it cannot validate and logs
   them rather than aborting the run.
5. **`classification_title` is not the artwork type.** On a Seurat it reads "oil on canvas".
   Filter on `artwork_type_title`. The index column is named `artwork_type` so nobody reaches
   for the wrong one. Table of verified vocabularies in `docs/aic-api.md`.
6. **`/artworks/search` caps at 1,000 records; `/artworks` is uncapped.** That difference is
   the whole reason the local index works. See ADR-0003's postscript.
7. **`.gitignore` patterns without a leading slash match at any depth.** A bare `data/` was
   silently excluding `app/data/fallback_artworks.json`, the bundled offline set.
8. **Tests must set `database_path`.** The `settings` fixture in `tests/conftest.py` points at
   a tmp file. Without it the suite reads and writes the developer's real index.
9. **A Screen Wake Lock is released whenever the tab stops being visible, and is not given
   back.** Same family as 1 and 2: the browser takes something away while you are not looking.
   Re-acquiring on `visibilitychange` is not a refinement of ambient mode, it *is* ambient
   mode. Also note that opening a second tab through browser automation did not hide the first
   one, so that path cannot be exercised that way — it was verified by releasing the lock by
   hand and firing the event, which is the same sequence the browser performs.

## Decisions already made

`QUESTIONS.md` is a settled record, not a list of open items — Karol ruled on all twelve on
2026-09-03. Read it before changing anything it covers, so a decision does not get relitigated.

The ones that constrain future work:

- **#8 is a standing rule, now in `CLAUDE.md`.** Ask before sustained automated traffic to an
  external service — anything running several minutes or making a substantial number of
  requests, even inside documented limits. A full `build_index.py` walk needs approval. A few
  calls to verify a field does not.
- **#10** Style and subject filters are wanted, but not at the cost of a crawl on their own.
  They have their own milestone, M3.5, to be batched with other indexing work.
- **#11** The scoring weights are accepted as heuristics, explicitly not as claims about art.
  Keep them easy to tune; keep the comments honest about being judgement calls.
- **#6** 1686 stays the top image width. `chooseWidth()` was checked and does scale with
  viewport x DPR; 1686 is simply the largest rung.
- **#3** The 5-line description clamp stays. No scrolling, no "more" affordance — it is an
  ambient display, not a dashboard.

One loose end. **#5 fullscreen is closed** — Karol tested `F` by hand on 2026-09-03 and it
works. It could never have been closed from here: `requestFullscreen()` needs a real user
gesture and a synthetic key event is not one.

- **#2 `S`** — Karol answered "leave it unbound until M4", but that answer was given against a
  question written in M1, before the settings panel existed. It exists now and `S` is its only
  entry point, so unbinding it would strand the Explore filters. Left bound, flagged in
  `QUESTIONS.md` #2, awaiting his word.


## Conventions worth matching

- `CLAUDE.md` is the contract; `app/`, `frontend/` and `tests/` each have their own.
- Fix the doc in the same commit as the code when reality disagrees with it. Several docs here
  carry corrections made exactly that way.
- Commit messages say *why*, and name what was found rather than just what changed.
- Tests assert ordering, never exact floats, so weights stay tunable.
- Fixtures are recorded real responses in `tests/fixtures/aic/`, never hand-written.
- Definition of done includes opening it in a browser and looking at it. Every rendering bug in
  the list above was invisible to a passing test suite.
