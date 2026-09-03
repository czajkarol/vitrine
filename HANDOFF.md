# Handoff

State of vitrine as of 2026-09-03. Written for whoever (or whatever) picks this up next.

---

## Where the project actually is

M0, M1 and M2 are complete and committed. M3 is complete apart from one scoped-down item.
`docs/roadmap.md` is accurate — it was reconciled against the code, not against intentions.

The app works end to end: it serves an artwork from a local SQLite index in ~19ms with no
network call, rotates on a timer, has a keyboard map, a metadata overlay, a settings panel with
Explore filters, and Curated mode backed by transparent scoring.

## Run it

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
uv run pytest                             # 150 tests, excludes live/e2e
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

**M4 — Settings and i18n** is the next milestone to work on. Note that **M3.5 sits above it
in the roadmap and is deliberately parked**: style and subject filters need a full re-crawl,
and Karol ruled they wait to be batched with other indexing work rather than triggering a
22-minute walk on their own. Do not start there just because it comes first in the file.

M4's groundwork is already there:

- The settings panel exists (`frontend/js/panel.js`), opens on `S`, closes on `Esc`, and pauses
  rotation while open. M4 adds language, ambient mode, and the AI toggles to it.
- Preferences persist through `GET`/`PUT /api/preferences`, a typed schema in
  `app/api/schemas.py`. Adding a preference means adding a field there and a key in
  `app/api/routes.py`. Interval, mode and artwork type are already wired.
- Every user-visible string is already keyed in one table, `MESSAGES` in `frontend/js/main.js`,
  including error messages. M4 moves that table to `frontend/locales/en.json` and `pl.json`.
  Nothing is hardcoded in markup except the panel's own labels in `index.html`, which need
  extracting.

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

Two loose ends:

- **#5 fullscreen** is the one genuinely unresolved item. `F` cannot be verified from
  automation because `requestFullscreen()` needs a real user gesture. Karol is testing by hand.
- **#2 `S`** — Karol answered "leave it unbound until M4", but that answer was given against a
  question written in M1, before the settings panel existed. It exists now and `S` is its only
  entry point, so unbinding it would strand the Explore filters. Left bound, flagged in
  `QUESTIONS.md` #2, awaiting his word.

## Prompt for a fresh session

Kept here so it is updated alongside the code rather than drifting in someone's notes. Check
the HEAD hash and the milestone line before reusing it.

```
Continue work on vitrine (lower case, always — it is in CLAUDE.md), an ambient digital-art
display: Python/FastAPI + vanilla JS + SQLite, showing public-domain artworks from the Art
Institute of Chicago. The project is Karol's; the Windows account is Filip's, so paths read
C:\Users\Filip — that is the machine, not the person.

Read first, in this order:
  1. HANDOFF.md      — state, how to run it, and eight traps that cost real time
  2. CLAUDE.md       — the project contract (plus app/, frontend/, tests/ variants)
  3. docs/roadmap.md — accurate; reconciled against the code, not against intentions
  4. QUESTIONS.md    — twelve settled decisions. Read before changing anything they cover.

M0-M3 are complete and committed (HEAD: a9526ac).

Start on M4 — Settings and i18n. Deliberately skip M3.5, which sits above it in the file:
style and subject filters need a full re-crawl, and Karol has ruled they wait to be batched
with other indexing work rather than triggering a walk of their own.

M4's groundwork already exists. The settings panel is built (frontend/js/panel.js, opens on
S, pauses rotation while open) and holds mode plus Explore filters. Preferences persist
through a typed GET/PUT /api/preferences. Every user-visible string is already keyed in the
MESSAGES table at the top of frontend/js/main.js, including error messages. M4 moves that
table to frontend/locales/en.json and pl.json, extracts the panel's own labels from
index.html, adds a language switch without reload, and adds ambient mode via the Screen Wake
Lock API.

Work autonomously through the roadmap as CLAUDE.md's working agreement describes: take the
next unchecked item, build it, tick it off, commit with a message saying why. Ask only for
credentials, irreversible actions, product decisions that change what the app is, or
sustained automated traffic to an external service. Fix a doc in the same commit as the code
when reality disagrees with it.

Do NOT run scripts/build_index.py without asking Karol first. It is 1,328 requests over
about 22 minutes, and his standing rule in CLAUDE.md covers exactly that. You should not
need it: data/vitrine.db already holds 57,607 scored artworks on this machine. It is
gitignored, so on a fresh clone the app degrades to AIC and then to the bundled fallback set
rather than breaking — that is the intended behaviour, not a fault to fix by crawling.

Three things this codebase takes seriously, each learned expensively:
  - Definition of done includes opening it in a browser and looking at it. Every rendering
    bug found so far was invisible to a passing test suite.
  - Do not invent AIC API fields. Verify against a live response, then record what you found
    in docs/aic-api.md.
  - img.decode() and requestAnimationFrame both never fire in a hidden tab. An ambient
    display is hidden much of its life. See traps 1 and 2 in HANDOFF.md before touching
    frontend/js/display.js.

One item still open: QUESTIONS.md #5, whether fullscreen (F) works. Karol is testing it by
hand; automation cannot supply the user gesture requestFullscreen needs. And #2 is flagged
rather than settled — read it before touching the S binding.
```

## Conventions worth matching

- `CLAUDE.md` is the contract; `app/`, `frontend/` and `tests/` each have their own.
- Fix the doc in the same commit as the code when reality disagrees with it. Several docs here
  carry corrections made exactly that way.
- Commit messages say *why*, and name what was found rather than just what changed.
- Tests assert ordering, never exact floats, so weights stay tunable.
- Fixtures are recorded real responses in `tests/fixtures/aic/`, never hand-written.
- Definition of done includes opening it in a browser and looking at it. Every rendering bug in
  the list above was invisible to a passing test suite.
