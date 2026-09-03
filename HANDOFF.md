# Handoff

State of vitrine as of 2026-09-03. Written for whoever (or whatever) picks this up next.

---

## Where the project actually is

M0 through M5 are complete and committed, apart from one scoped-down item in M3 (M3.5, parked
deliberately — see below). M6 is three items in: `/api/stats`, structured logging with request
ids, and the CI workflow that was already there. `docs/roadmap.md` is accurate: it was
reconciled against the code, not against intentions, and is ticked as work lands.

The app works end to end: it serves an artwork from a local SQLite index in ~19ms with no
network call, rotates on a timer, has a keyboard map, a metadata overlay, a settings panel with
Explore filters, and Curated mode backed by transparent scoring. It speaks English and Polish,
switchable without a reload, and will hold the screen awake if asked.

AI is wired end to end. Pinning the overlay with `I` asks for an interpretation; it is cached,
capped and breakered. Two real providers are built, and a key can be pasted into the settings
panel and takes effect without a restart. With nothing configured — the default — the feature
simply is not offered, which `CLAUDE.md` requires and which is worth re-checking after any
change here.

## Run it

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
uv run pytest                             # 334 tests, excludes live/e2e
uv run pytest -m live                     # 9 tests: the real AIC API, and the AI
                                          # providers if their keys are in .env
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

`data/vitrine.db` is gitignored, so a fresh clone starts with no index and serves from AIC,
then from the bundled fallback set. To build the index:

To run with AI, using the provider that needs no key and no network:

```bash
AI_ENABLED=true AI_PROVIDER=mock uv run uvicorn app.main:app
```

With a real provider, put `AI_ENABLED`, `AI_PROVIDER` (`anthropic` or `openai`) and the
matching key in `.env` — or skip all of that and paste a key into the settings panel, which
overrides `.env` and needs no restart. Name a provider in `.env` without its key and the
feature stays off with a warning rather than the app failing to start — worth re-checking after
any change there, because "AI is an enhancement, never a dependency" is a `CLAUDE.md`
non-negotiable.

`uv sync --all-extras` includes the `keyring` extra; without it a pasted key goes in
`data/vitrine.db` unencrypted, and the panel says so.

```bash
uv run python scripts/build_index.py             # full walk, ~22 min at 1 req/s, resumable
uv run python scripts/build_index.py --limit 5000
uv run python scripts/build_index.py --score-only
uv run python scripts/build_index.py --explain <artwork_id>
```

## What to do next

**M6 — Finish.** Four items left.

**Playwright smoke tests needs a decision before it needs work.** Neither `playwright` nor its
browser binaries are installed on this machine, and installing them is a few hundred megabytes
of download — Karol's call, not one to make on his behalf. The five flows the roadmap wants are
in `docs/testing.md`. Everything else in M6 is unblocked.

- **README written properly.** No longer a pure stub: the bring-your-own key section was
  written during M5, because `docs/ai-system.md` makes documenting the unencrypted fallback a
  condition of having one. Everything else in it is still the stub text.
- **Screenshots.** Needs a decision on where they live and whether binaries belong in the repo.
- **ADRs reviewed against what was actually built.** ADR-0008 was already reversed once in
  flight; the others have not been read against the code since they were written.

What the two finished items put in place:

- **`/api/stats`** — cache hit ratio, provider latency, AIC error rate, today's spend, index
  size. Counters are in `domain/metrics.py`: pure, in memory, from process start. The only
  figure that survives a restart is the AI spend, because it is the only one anything enforces
  against. Nothing in the frontend reads this endpoint; it is for whoever is running the thing.
- **Logging** — `core/logging.py` and `api/middleware.py`. One id per request, from a
  `ContextVar` read at format time, so no existing log call had to change. `LOG_FORMAT=json`
  switches to one object per line. Every record goes through `redact_secrets()`, which catches
  a key-shaped token wherever it came from — a net under the source-level redaction, not a
  replacement for it. uvicorn's access log is silenced because the middleware logs its own
  line; `uvicorn.error` is adopted so the banner matches everything else.

**Still outstanding from M5, and it needs Karol:** neither real provider has been verified
against its real API. **`uv run pytest -m live` with a key in `.env` is the manual step**, and
it is the only thing that can catch a wrong default model id or `max_completion_tokens` being
wrong for the model in use. A fake key was pushed all the way through the BYO path in a
browser on 2026-09-03 and came back a clean 401 — which proves the wiring and nothing about
the model ids.

How bring-your-own keys fit together:

- `repositories/credentials.py` holds two backends and chooses once, at startup. The keyring
  is *probed*, not imported: `import keyring` succeeds on a machine whose credential store
  does not work, and the backend it resolves to raises only when used. Failing the probe means
  SQLite, unencrypted, and the panel says so before anything is typed.
- `services/ai_credentials.py` decides which provider is live. A saved key outranks `.env`,
  `AI_ENABLED` is not consulted for it — pasting a key is the decision to enable the feature —
  and swapping providers resets the circuit breaker, because the failure count belonged to the
  provider that earned it.
- `app/api/errors.py` exists because FastAPI's default 422 echoes the rejected input, so a
  malformed key came back out in the error body. It drops `input` and `ctx` from every
  validation error. See the note in "Things that will bite you".
- The one text field in the app is the key field, which is why Esc is now exempt from the
  "shortcuts are inert while typing" rule in `shortcuts.js`.

Adding the second provider did not change `providers/ai/base.py`, which is the result
`docs/ai-system.md` set that exercise up to test. It did produce `providers/ai/http.py` — the
client, POST, error map and redaction both real providers share. Shared implementation, not a
shared interface.

**Streaming over SSE** is described in `docs/ai-system.md` as a refinement to do after the
non-streaming path works and is cached. It is not a roadmap item yet and does not need to be
one before M6.

How the AI side fits together, so it does not have to be re-derived:

- `domain/interpretation.py` is the validated shape and the composite cache key;
  `domain/prompts.py` builds the prompt and owns `PROMPT_VERSION`, which is part of that key.
- `providers/ai/base.py` is the Protocol, the errors and `parse_interpretation()`, which every
  provider shares because "the model returned something unparseable" is not vendor-specific.
  `http.py` is the transport both real providers share. `factory.py` is the only place a
  vendor name is mapped to a class, and it returns `None` — a warning, not a crash — when a
  provider is named without its key.
- `services/interpretation.py` is the orchestration: cache chain, budget, breaker, timeout.
- The frontend asks only when the overlay is *pinned* with `I`, never on the overlay's own
  flash at every rotation. That distinction is the feature's entire cost model — check it is
  still true after touching `main.js`.
- `/api/health` carries the AI block. The frontend reads it at boot rather than asking for an
  interpretation and being refused.

Note that **M3.5 sits above M4 in the roadmap and is deliberately parked**: style and subject
filters need a full re-crawl, and Karol ruled they wait to be batched with other indexing work
rather than triggering a 22-minute walk on their own. Do not start there just because it comes
first in the file.

What M4 put in place, and what M5 built on:

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
  mode, artwork type, language and ambient are wired. The table stores strings, so a boolean
  is written `"1"`/`"0"` and only `"1"` reads back as true. The BYO provider name lives in the
  same table under `ai_byo_provider`, but deliberately *not* in `PreferencesResponse`: it is
  written by `PUT /api/ai/key` alongside the key itself, and letting the browser set it
  independently would point the app at a vendor whose key it does not have.
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
9. **Chrome caches ES modules hard, and a stale one fails as a blank screen.** After editing
   a JS module, a plain reload can still run the old file — the symptom is
   `does not provide an export named X` for an export that is plainly there. Refetch with
   `fetch(url, { cache: 'reload' })` for each changed file, then reload. There is no build
   step and no cache-busting query, so this will keep happening.
10. **FastAPI's 422 echoes the rejected input back to the caller.** Ordinarily helpful; not
   when the input is an API key. A key with a stray character in it came back out in the error
   body, and `SecretStr` does not stop it — pydantic reports what it was handed, before the
   field type applies. `app/api/errors.py` strips `input` and `ctx` from every validation
   error. Nothing about the original code read as a leak. It was found by a test that sent a
   malformed key and searched the response for it, which is the only way it was going to be.
11. **A Screen Wake Lock is released whenever the tab stops being visible, and is not given
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
