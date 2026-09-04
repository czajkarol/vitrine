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

- [x] `domain/rate_limit.py`: a pure token bucket, the clock passed in — with a rolling
      hourly ceiling over it, because a bucket alone permits its sustained rate forever and
      forever is the failure mode a display left running has
- [x] Applied to `/api/artwork/random` and `/api/image/{image_id}`; 429 with `Retry-After`.
      Burst 10, one token per 3s, 400 an hour, all `RATE_LIMIT_*` in `.env`
- [x] The frontend waits out `Retry-After` calmly and never retry-storms — the manual
      advance is held for exactly that long, and the rotation clock backs off by the same
      amount instead of its usual 20 seconds
- [x] **The limiter caused the storm it prevents, and the browser check found it.** An
      `<img>` cannot see a `429`, so a refused image read to the display as a dead one: it
      dropped the artwork and asked for another immediately, spending more of the budget
      that had just refused it. 27 refusals and no recovery. The unit being limited is now
      an *advance* — an allowed artwork request grants a credit its image spends — which
      took the same run to 2 refusals and a clean recovery at the exact `Retry-After`
- [x] Commit

## M10 — Canonical facets

The largest milestone, and it needs **no AIC traffic**: the raw terms are already in SQLite.

- [x] `domain/vocabulary.py` — the canonical facet map, pure, with every dropped value listed
      and commented. Only merges, relabels and drops are written by hand; everything else
      derives its own facet, so nothing is silently lost and the map stays short. Broad, per
      the owner's ruling: 30 type facets, 585 style, 1,611 subject, of which 26 / 82 / 173
      clear the offering bar. `MAX_FILTER_OPTIONS` 30 → 60 to match
- [x] Migration 008 `artwork_facets`, with artwork type folded in as `type.*` so all three
      groups share one query shape. The primary key deduplicates, which is what fixed the
      counts: the panel used to imply 3,169 portraits where there are 2,126
- [x] `build_index.py --retag`, and run automatically after a crawl — 131,264 rows over
      57,607 artworks in 1.7s, no network. The crawl also tags in the same transaction it
      writes, so a row can never be indexed and invisible to every filter
- [x] Exclusion: multi-valued per group, `NOT IN`, offered as a sub-list under each group
- [x] Dependent counts between the groups, leave-one-out, zero-count options disabled not hidden
- [x] Facet labels in `locales/`, Polish written as UI copy rather than as translation — 146
      of them. `en.json` deliberately has none: the server's label is the English label
- [x] ADR-0009 — canonical facets over AIC's raw terms
- [x] **Two things the live vocabulary taught, after the code was written.** Stripping a
      parenthetical looks like tidying and is not — it merged `orange (color)` with
      `orange (fruit)`, and `edo (african)`, the Edo people of Nigeria, with
      `edo (japanese period)`. And a slug cannot be reversed into a label: `chimú` became the
      key `chim` and the label "Chim". Both are tests now
- [x] **And one the browser caught.** Re-fetching the counts on every change rebuilt the radio
      lists, and a fresh radio only knows the `defaultChecked` it was built with — so the panel
      read "Any style" while the rotation was still filtered, and clicking "Any" to clear it
      fired no event because it already looked checked
- [x] Commit

## M11 — Modes, scoring explained, favourites

- [x] Mode options rendered as name + quiet description; the em dashes leave the strings
- [x] `GET /api/scoring` and an `i` beside Mode explaining the weights in both languages,
      with the numbers taken from the code — a collapsed "How Curated ranks" under the mode
      list, showing each signal's share of the total. Retuning a weight updates it
- [x] Migration 009 `artwork_feedback` — no foreign key, with a small snapshot. The foreign
      key would have failed on exactly the setup a new user has: the second and third tiers
      serve artworks that are not in the index at all
- [x] `L` likes, `X` hides, a heart in the overlay, `GET`/`PUT`/`DELETE /api/favorites`.
      Hidden artworks are excluded in every mode, plain random included. The like state
      travels with the artwork rather than as a second request per rotation
- [x] "For you" as a third mode over `domain/affinity.py`, falling back to Curated below
      about five likes and saying so — `personalised: false` on the response, and one line
      on screen. Ranking is `curated × (1 + α · affinity)`, so quality still bounds it
- [x] ADR-0010 — personalisation from explicit feedback only
- [x] A sixth Playwright flow, which had to argue for itself: a favourite surviving a
      reload is the one thing that crosses every layer in a way no smaller test can
- [x] Commit

## M12 — Data, setup, and other sources

- [x] `scripts/export_index.py` — corpus tables only, into a fresh file, `VACUUM`ed. The
      allow-list and the SQL live in `app/repositories/corpus.py`, so the two halves of the
      round trip cannot drift and both are testable without a subprocess. 57,607 artworks
      in 1.5s; **57.8MB, not the 25–35MB the plan estimated** — `lqip` is 15MB of it, and
      it stays, because it is what starts the crossfade before the image arrives
- [x] `scripts/fetch_index.py` — merge a published export without touching preferences,
      history or credentials. HTTPS only, a declared length within plausible bounds, and
      the file itself read before anything is merged out of it; `--sha256` for the check
      that says it is *the* file. Verified against the real corpus: 57,607 artworks merged
      in 1.2s into a database whose language preference, favourite and stored key all
      survived, then opened in a browser
- [x] `docs/setup.md`, verified by following it on a clean checkout — and the check earned
      its place immediately, see the item below
- [x] `docs/data.md` — what is stored, what is rebuildable, what may be published and why the
      database is not committed
- [x] ADR-0011 — distribute the index as a release asset, never in Git
- [x] **`.env.example` could not be copied verbatim, which is exactly what step 3 tells you
      to do.** python-dotenv strips a trailing comment only when a value comes *before* it,
      so `AI_PROVIDER=  # mock | anthropic | openai` on an empty key read the comment as the
      value: a `literal_error` at startup on a clean checkout. `AI_MODEL=` had the same
      shape and was worse — a plain `str`, so it took the comment as a model id and failed
      later, at the provider. Both comments moved to their own line
- [x] ADR-0012 (Proposed) — additional art sources, and what a second one would actually cost.
      Written from four requests to Cleveland's own API rather than from the plan's table,
      which turned out to be wrong on two of five columns: **41,512** CC0 records with an
      image, not ~64k, and **no IIIF at all** — three fixed URLs, of which `full` is a TIFF
      browsers cannot display, so two usable sizes. The finding that decides it is a field
      gap the table did not mention: Cleveland has no `lqip`, no `alt_text` and no `color`,
      which are the crossfade, the AI prompt's grounding, and the overlay scrim. Eight
      things a second source costs, of which one is an API client
- [x] ADRs re-read against the code, `docs/architecture.md` and `HANDOFF.md` reconciled —
      0009's facet counts (30/585/1,611, of which 26/82/173 clear the bar) and 0010's
      threshold, α and formula still match the code exactly. 0003 gained a third postscript:
      one of its costs assumed walking AIC was the only way to obtain a corpus. And
      `architecture.md` was missing `artwork_feedback` and `schema_migrations` from its
      table list, an M11 gap
- [x] Commit

---

## M13 — Navigation, filters, and a third verdict

The UX round. Most of it is one idea applied five times: a control should say what it does and
what state it is in, and there should be one of it.

- [x] **One tri-state control per facet**, replacing three lists of radios plus three collapsed
      lists of checkboxes — the same sixty facets written twice, in two places, meaning two
      different things. Click to include, again to exclude, again to clear. State carried three
      ways at once: a glyph, a colour, and a word in the `aria-label`, because any one alone is
      a guess and green-versus-red is the worst possible pair. `frontend/js/filters.js` is new;
      `panel.js` kept the orchestration
- [x] **Inclusion is multi-valued and ORed inside a group**, ANDed between groups, with exclusion
      NOT-ed over all of them. The operator had to change with the arity: `type.painting AND
      type.print` is empty by construction. Painting-or-print is 26,120 indexed works where
      painting alone is 1,816. ADR-0014
- [x] Groups collapse, carry a badge saying what is on inside them, open themselves when
      something is, and gain a search box past twelve options. A selected row always shows
      whatever the search says, because hiding a selection makes it invisible rather than absent
- [x] **Inclusion and exclusion sanitise differently**, and the asymmetry is the point: a dropped
      exclusion shows you more than you asked for and you can see it, a dropped inclusion
      silently stops filtering. `_included_facets` keeps an unrecognised key so it matches
      nothing, rather than dropping it so it constrains nothing
- [x] **Artwork history** — `frontend/js/history.js`, twenty deep, arrows and a button. Payloads
      rather than decoded images: a decoded 1686px bitmap is several megabytes and this app runs
      for hours, and the image comes back out of the browser's own HTTP cache. Cleared when the
      source changes, because a stack crossing museums would offer to return to an artwork the
      current one cannot show
- [x] **`D` dislikes**, a third verdict between `L` and `X`. The original pair had nothing in the
      middle: `hide` is a hard exclusion, so it could never also mean "less of this". A dislike
      only ranks, so it counts against the affinity profile harder than a hide does — the nudge
      is all the user gets for pressing the key. Migration 010
- [x] **A left click in fullscreen takes everything but the artwork away**, and movement does not
      bring it back — that last part is the whole request. A second click restores it, and both
      say so once on the status line, because a click that hides every control also hides the
      way back
- [x] **Rotation pauses while the details are expanded.** The stretched idle fade was half of
      this problem; the text staying put while the picture underneath it changed is no better
      than the text going away
- [x] **The `i` control is on every artwork**, and is a *details* toggle rather than an expand
      button. It used to appear only when the description was clamped — right about the clamp,
      wrong about the control: on the seven artworks in eight with no description at all it
      vanished, which reads as a fault rather than as an absence. It now opens the description
      where there is one and four catalogue facts either way, all of which were already on the
      response and on screen nowhere. `QUESTIONS.md` #3, amended a second time
- [x] **Expanded is a different size.** The whole panel steps up, the measure widens, and the
      colour brightens: 1.0625rem at `--fg-dim` is right for a caption glanced at across a room
      and wrong for four hundred words
- [x] **`?` opens a translated keyboard map** in the settings panel. Thirteen shortcuts were
      documented only in a file nobody using the app reads
- [x] Polish "How Curated ranks" rewritten as UI copy rather than as translation — "Skąd się
      biorą te dzieła", not a clause-for-clause rendering of the English beside it
- [x] ADR-0014 — one tri-state control per facet, and OR inside a group
- [x] **Four things the browser check changed, and one the tests did.** `display: grid` outranks
      the user agent's bare `[hidden]` selector, so the catalogue facts sat on screen at rest
      under a caption nobody had expanded — the same trap `.ov-button[hidden]` was already
      patched for, which makes it the second instance and a `HANDOFF.md` gotcha. Switching to
      Cleveland left Curated selected in the panel while the display served plain random picks.
      The panel drew its interval menu before boot had loaded a locale, five missing-translation
      warnings' worth. The scrim is a gradient over the overlay's own box, so expanded to most of
      the screen it stopped being a scrim and the title sat over gold leaf on a triptych. And
      Playwright flow 7 found, on its first run, that the artwork-type group is called
      `artwork-type` while its facets are `type.*` — code matching the shared exclusion list on
      the group's own name silently dropped every exclusion in that group
- [x] Commit

## M14 — Described for listening

An accessibility feature on the existing AI system, and the one place in this app where a wrong
sentence is not recoverable: the reader is the person who cannot check it against the screen.

- [x] `VisualDescription` model, `VISUAL_INSTRUCTION` prompt, `VISUAL_PROMPT_VERSION` versioned
      separately from `PROMPT_VERSION` — retuning the interpretation must not discard every
      description, which is the more expensive of the two to regenerate
- [x] **Grounded in `thumbnail.alt_text`, and the display says so.** No model sees the image. The
      prompt's two strongest rules are take everything visual from the museum's own words, and
      *match the length of your source* — padding a one-clause alt text is inventing, and a
      listener cannot tell the difference. The context sent is narrower than the
      interpretation's: `department` and `place_of_origin` are dropped, because they say nothing
      about what an artwork looks like and are exactly what a model reaches for when it has
      nothing else
- [x] **Refused before the call when there is nothing to go on** — `is_describable`, 422
      `access_not_describable`. Upstream of the money, because the audit cannot happen downstream
      of it. All 57,607 indexed works have `alt_text`, so this bites only on the other tiers
- [x] `grounded_in` on the response and a line on screen naming which museum field the words came
      from. Not a disclaimer bolted on — it is the sentence that makes the feature honest, so it
      renders with the text rather than behind a fold
- [x] **Anthropic only as a capability, not a flag** — `VisualDescriptionProvider`, a second
      `runtime_checkable` Protocol. Anthropic and the mock implement it; OpenAI does not.
      `/api/health` reports `ai.describes` and the control is not offered when it is false. A
      vendor name above `providers/` is forbidden by `CLAUDE.md`, and a method on the shared
      Protocol would have made OpenAI implement it by raising
- [x] **TTS is the browser's own `speechSynthesis`** — no key, no per-word bill, works offline.
      Two API traps handled: voices load asynchronously and are empty on first call in Chrome, so
      the list is primed at boot; and a long utterance is cut off in some builds, so the text is
      split at sentence boundaries, which also makes `cancel()` responsive
- [x] **Replay is a control, not a second request.** The text is on screen and the server has it
      cached, so it costs nothing — which is what lets the display offer it without asking
      anyone's permission
- [x] Its own labelled region, `role="region"` with a name, `aria-live`, real buttons in the tab
      order, reachable by `A` from the keyboard
- [x] **Asking for one puts a five-minute floor under the rotation** without touching the saved
      interval. A spoken description takes most of a minute; at the 30-second rung the artwork is
      gone before the end of it. A floor rather than an assignment, so the user's own choice comes
      back when it lifts
- [x] Both kinds share one provider, budget, breaker, timeout and cache. Two budgets would have
      been two numbers to reason about and one of them silently spent. `kind` joins the cache key
      only when it is not the default, so nothing cached before this was invalidated; migration
      011 adds it as a column too, for the same reason `prompt_version` is one
- [x] **Costs measured and written down** — `docs/ai-system.md`. About 0.4¢ per description at
      `claude-sonnet-5`, 0.7¢ at the output cap; the 200/day budget is $0.75–$1.48. Speech is
      free, and a cloud voice would have been the *expensive* half, because it bills per playback
      where the model call bills once and is then cached
- [x] ADR-0015 — grounded in the museum's alt text, not in the image. The alternative that was
      not taken is the interesting half of the record
- [x] Commit

## M15 — Cleveland, as a live source

ADR-0012 said no and priced the no at eight items. The owner asked for Cleveland without feature
parity, which is a different purchase: most of the eight are consequences of *indexing*.

- [x] `app/providers/source.py` — `ArtworkSource` finally has a second implementation, and it is
      deliberately small because it is the interface for a *live* source. AIC does not implement
      it: indexed, scored and faceted is a much larger surface than a second museum is worth
- [x] `app/providers/cma/client.py` — the only module that knows CMA's JSON. 41,512 CC0 records
      with an image, no key, no published rate limit. Two requests per artwork: one for the
      total, one for a sample around a random offset
- [x] **No IIIF, so `SourceArtwork` carries a finished URL.** Three fixed URLs per record, of
      which `full` is a TIFF browsers do not render and `print` is several megabytes. `web` is
      the only usable one, and `chooseWidth()` and the ADR-0008 proxy are skipped entirely
- [x] Selectable in the panel. Picking it clears the filters and the history and disables Curated
      and "For you" with a line saying why — they rank against a score only the index carries
- [x] **Migration 010: `artwork_feedback` gains `museum` and a composite key.** The one item of
      ADR-0012's eight that could not be deferred: artwork id 1 is a real record at both museums,
      and a favourite keyed on `artwork_id` alone would let a Cleveland print un-like an Art
      Institute painting
- [x] Per-museum attribution in both locales. CC0 for Cleveland; the CC BY clause stays on the
      Art Institute's half, where the licence actually applies
- [x] **The AI features are not offered on a Cleveland artwork**, and ADR-0012 asked for that to
      be a decision taken out loud rather than arrived at by accident. Two reasons agree: the
      server cannot look the artwork up, and there is no `alt_text` to ground either prompt
- [x] One closed list of ten artwork types with live totals, cached an hour per process. No facet
      endpoint exists and deriving one would mean the walk this milestone exists to avoid
- [x] Fixtures in `tests/fixtures/cma/` are captured real responses, per the tests' own rule
- [x] ADR-0013, superseding ADR-0012 and keeping its research
- [x] Commit

## M16 — Documentation

- [x] ADR-0013, 0014, 0015 written; ADR-0012 marked superseded rather than left contradicting
      the code, with a note on the one alternative it rejected that was then taken
- [x] This roadmap, `docs/product-spec.md`, `docs/architecture.md`, `docs/ai-system.md`,
      `docs/testing.md`, `docs/data.md`, `HANDOFF.md`, `README.md` reconciled with the code
- [x] `QUESTIONS.md` #3 amended a second time — the `i` control is on every artwork now, which
      is a further change to a ruling that already carried one amendment
- [x] **Polish translations of museum descriptions: assessed, and deliberately not built.** See
      "Not doing" below for the numbers and the reason
- [x] **A personal address had got back into `.env.example`**, which M7 removed on purpose. It is
      the file `docs/setup.md` step 3 tells you to copy, so a real address in it ships to whoever
      clones this. Reverted
- [x] Commit

---

## M17 — A dead filter row, a screen that stays awake, and saved combinations

Six items from the owner, plus two bugs found while reproducing the first one.

- [x] **An excluded facet could not be turned back on.** Not a stuck state: two
      `/api/filters` answers arriving in the wrong order. An exclusion is a NOT over the
      whole facet table and is measurably the slower query, so the answer saying "excluded"
      could land *after* the answer to the click that cleared it — and a count of zero on a
      row whose state had just gone back to `off` is exactly the pair `buildRow` disables.
      `loadFilters` numbers its requests and drops any that is not the newest. ADR-0014
      amended
- [x] **The same control offered `exclude` on Cleveland, which has no facet layer to
      exclude over.** The third click produced a value the server rejected and the next
      redraw dropped, so the row snapped back to off. Two states there, and the hint above
      the groups says which cycle is running. Found in a browser. ADR-0013 amended
- [x] Flow 7 grew two parts for both, and neither could be written with `page.route`: a sync
      route handler sleeps on pytest's own thread and stops the second click leaving
- [x] **Going fullscreen turns ambient mode on** and asks for the wake lock. The
      off-by-default argument held while the app was a window among windows and does not
      hold in fullscreen. It must not overrule a hand-set OFF (`ambient_by_hand`), must not
      touch the preference where there is no Wake Lock API, and must not claim the screen
      will stay awake unless a lock was actually acquired. `docs/product-spec.md` amended
- [x] **The settings panel explains the API key in plain language**, both locales — where it
      goes, what never happens to it, and what a keyring is. Every claim checked against
      the code first
- [x] **Coins excluded on a fresh install**, seeded into the `exclude` preference rather
      than compiled in, so it arrives as an ordinary exclusion the badge shows and one click
      undoes. 1,220 of 57,607, not the 4,000-odd assumed
- [x] **Saved filter combinations**, as named presets: `filter_presets` (migration 012), the
      panel's list, and a note when a preset holds facets the index no longer offers. No
      ADR — every hard call in it was already taken by ADR-0011, ADR-0014, or the rule that
      a filter may never silently widen
- [x] **`H` keeps the artwork up five minutes longer**, repeatable to an hour. Three designs
      were put to the owner and this one chosen: it ends by arithmetic rather than by an idle
      timer, so the unattended promise holds without anything having to guess whether somebody
      is still in the room. Only the deadline moves — not the interval, not the floor, not the
      mode — so it is a duration and not a state
- [x] `README.md` no longer says "Built for a second monitor."
- [x] Commit

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
- **Polish translations of the museum's `description`** — assessed 2026-09-04, deferred with
  numbers rather than declined. 6,681 of 57,607 indexed artworks have a description (11.6%),
  averaging 624 characters, so on-demand translation is roughly 350 input and 250 output tokens
  per artwork per language — well under a cent each, cached, and not the reason to wait.

  The reasons to wait are the other two. It is a *third* generated kind: a third prompt version,
  a third cache kind, a third UI state, and a third thing sharing the one daily budget that M14
  just gave a second claimant. And AIC's `description` is CC BY 4.0, so a translation is a
  derivative work — it has to carry the attribution *and* be marked as a machine translation
  rather than presented as the museum's own words, which is a licence question and a design
  question before it is a prompt.

  If it is built it is its own milestone, and the shape is known: `kind="translation"` on the
  existing cache key, its own prompt version, and a line in the overlay saying the Polish is
  generated. The owner asked for it to sound written rather than rendered, which is the same
  instruction the facet labels and the scoring copy already follow.
