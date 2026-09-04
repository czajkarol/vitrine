# Handoff

State of vitrine as of 2026-09-04. `CLAUDE.md` is the contract; this file is what you cannot
derive from it. `docs/plan-improvements.md` was the agreed work through M12 and is now spent;
read it for the reasoning behind M7–M12, not for what to do next.

---

## Where the project is

**Every milestone through M16 is complete.** The roadmap is ticked against the code, not against
intentions.

The app works end to end. It serves an artwork from a local SQLite index in ~19ms with **no AIC
call at all**, rotates on a timer, has a keyboard map, a metadata overlay set in a serif, a
settings panel, and a Curated mode backed by transparent scoring. English and Polish, switchable
without a reload. Ambient mode holds a Screen Wake Lock.

The index holds **57,607 artworks**, all scored, plus 84,190 raw style/subject rows and
131,264 canonical facet rows. `data/vitrine.db` is 67MB and gitignored; the publishable
subset of it is 57.8MB.

**Three things arrived after M12 and each changed the shape of something.**

*Filters became one control per facet* (M13, ADR-0014). A facet has three states — off, include,
exclude — so its control cycles through three, and there is one list per group instead of two.
Inclusion is multi-valued and **ORed inside a group**, ANDed between groups. That reverses one
sentence of `docs/product-spec.md`, and the reversal is narrow: the old argument for radios was
about the operator, not the arity. M13 also added a browser-side back stack, a third verdict
(`D`, between like and hide), a fullscreen click that takes everything but the artwork away, and
`?` for a keyboard map that previously existed only in a file nobody using the app reads.

*The AI system grew a second thing it produces* (M14, ADR-0015). `A` asks for a spoken visual
description and reads it aloud through the browser's own speech synthesis, which costs nothing.
**No model sees the image**: it is written from AIC's own `alt_text`, and the display says so on
every screen that shows one. An artwork with nothing visual in its metadata is refused before a
call is made. Anthropic only, expressed as a capability Protocol rather than a vendor check.

*There are two museums* (M15, ADR-0013). Cleveland is a live source — never indexed, never
scored, never faceted — selectable in the panel, with Random only and one filter. ADR-0012 priced
a second source at eight items and recommended against it; not indexing dodges or narrows five of
the eight, which is why this was affordable and why ADR-0012 was not wrong.

AI is still off by default and still an enhancement, never a dependency. With nothing configured
neither feature is offered — that is a `CLAUDE.md` non-negotiable and is worth re-checking after
any change near it.

The two things still open are the owner's rather than the next agent's — see Outstanding. Both
predate this round and one of them matters more now: nobody has ever called a provider with a
working key, and the accessibility feature runs on the same unverified default model id.

Since M10 the filters run on a canonical facet layer rather than AIC's raw terms (ADR-0009),
there is a third mode built on explicit feedback (ADR-0010), and the corpus can be exported to a
publishable file and merged back without disturbing anything personal (ADR-0011). That last
one is what makes a second install cheap: 57,607 artworks in about a second, and no AIC
traffic at all.

M8, M9 and M13 each changed more than their own list. Seven bugs that a passing suite could not
see turned up as soon as the app was opened and looked at, and all of them are in the Gotchas
below. The pattern is consistent enough to be worth stating: **every rendering bug in this
project has been invisible to the test suite**, which is why the definition of done says to open
it in a browser.

## Run it

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload      # http://127.0.0.1:8000
uv run pytest                             # unit + contract; excludes live and e2e
uv run pytest -m live                     # the real AIC API, and the AI providers if keyed
uv run pytest -m e2e                      # nine Playwright flows; needs `playwright install chromium`
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

587 tests in the default run, plus 9 e2e flows and 9 live tests, both deselected by default.
The e2e run takes about a minute; flow 9 waits out a real rotation interval and is the only
slow one.

```bash
uv run python scripts/build_index.py             # full walk: 1,328 requests, ~30 min, resumable
uv run python scripts/build_index.py --limit 5000
uv run python scripts/build_index.py --score-only
uv run python scripts/build_index.py --explain <artwork_id>
```

```bash
uv run python scripts/export_index.py                         # → dist/, no network, ~1.5s
uv run python scripts/fetch_index.py --file dist/vitrine-index.sqlite
uv run python scripts/fetch_index.py --url https://... --sha256 <digest>
```

A fresh clone has no index and serves from AIC, then from the bundled 30-record fallback set.
`AI_ENABLED=true AI_PROVIDER=mock` runs the AI path with no key and no network.

## Constraints that must not be relitigated

- **Ask before sustained external traffic.** Several minutes, or a substantial number of
  requests, even inside AIC's documented limits. A full `build_index.py` walk needs approval; a
  handful of calls to check a field does not. `CLAUDE.md`, `QUESTIONS.md` #8.
- **Public domain only**, enforced at index time and at display time. ADR-0007.
- **No frontend framework, no build step.** ADR-0005.
- **`domain/` imports nothing outward**, only `providers/aic/` knows AIC's JSON shape and only
  `providers/cma/` knows Cleveland's, only `providers/ai/` names an AI vendor, config is
  injected. `ruff` enforces the `httpx` half of this. `docs/architecture.md`.
- **AI is an enhancement, never a dependency.** No key configured must mean the feature is not
  offered, not that anything fails.
- **Never hardcode the IIIF base**; it arrives on every AIC response and is remembered in
  `preferences`.
- **Scoring weights are product heuristics, not claims about art.** Keep them tunable; tests
  assert ordering, never values. ADR-0006, `QUESTIONS.md` #11.
- **The index is a cache, not truth.** AIC can unpublish an image at any time. ADR-0003.
- **The AI features apply to indexed artworks only.** Both prompts are grounded in AIC's own
  `alt_text`, and a source without one would need a different prompt or no AI at all. ADR-0013
  takes that decision explicitly; `canInterpret()` in `frontend/js/main.js` enforces it.
- `QUESTIONS.md` is a settled record of twelve rulings, not an open list. Read it before
  changing anything it covers. Two were reopened deliberately in M7 — #2 (`S` toggles) and #3
  (the description gains an expand affordance) — and #3 again in M13, when the `i` control became
  a details toggle shown on every artwork. Each carries a dated amendment in place. That is how a
  ruling changes here. Contradicting one in the code and leaving this file saying the opposite is
  not.

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
    `node_modules`, so no test runner (ADR-0005). Playwright covers nine smoke flows and no
    more, and a tenth has to argue for its slot. Most of the bugs in this list were invisible to
    a passing suite and were found by opening the app and looking at it, which is why the
    definition of done says to — but note that #18 was found by an e2e flow rather than by eye,
    and #23 by opening the app and then *waiting*, which is the case for the two flows that
    cover rules existing nowhere but in the browser.
13. **`.gitignore` patterns without a leading slash match at any depth.** A bare `data/`
    silently excluded `app/data/fallback_artworks.json`, the bundled offline set.
    `QUESTIONS.md` #9.
14. **`data/vitrine.db` holds a secret.** When there is no OS keyring, a pasted API key sits
    unencrypted in the same file as the index. Never commit, publish or attach it.
    `scripts/export_index.py` builds a publishable copy from an *allow-list* of corpus tables
    into a fresh file — never by deleting from a copy of that one, because a deny-list is
    wrong by default the moment somebody adds a table. ADR-0011, `docs/data.md`.
15. **python-dotenv strips a trailing comment only when a value comes before it.**
    `AI_PROVIDER=  # mock | anthropic | openai` on an *empty* key reads the comment itself as
    the value, so copying `.env.example` verbatim — which `docs/setup.md` step 3 tells you to
    do — made the app refuse to start with a `literal_error`. `AI_MODEL=` had the same shape
    and was quieter and worse: a plain `str`, so it took the comment as a model id and failed
    later, at the provider. Both comments now sit on their own line, and any new empty key in
    that file must too. Invisible to the whole suite, because the tests build `Settings`
    directly and the e2e fixture strips `AI_*` out of the environment.
16. **A WAL database copied without its `-wal` sidecar is missing its most recent writes.**
    Which is why an export is written in the default rollback journal mode rather than WAL:
    the deliverable is one self-contained file. `app/repositories/corpus.py`.

17. **`display: grid` outranks the user agent's `[hidden] { display: none }`**, which is a bare
    attribute selector and loses on specificity. This has now caught the same codebase twice —
    `.ov-button[hidden]` in M8, and `.ov-extra[hidden]` in M13, where the catalogue facts sat on
    screen at rest under a caption nobody had expanded. Any new element that both sets `display`
    and is toggled with `hidden` needs its own `[hidden]` rule. `frontend/css/app.css`.
18. **A group's name in the markup and its facet namespace are not the same string.** The
    artwork-type filter group is `artwork-type`; its facets are `type.*`. Two of the three groups
    have the same string for both, so style and subject worked and artwork type silently dropped
    every exclusion — a facet clicked to "exclude" snapped back to "off" on the next redraw. The
    namespace is now carried explicitly as `prefix` beside `group`. Found by Playwright flow 7 on
    its first run, which is the whole argument for that flow existing.
19. **The overlay scrim is a gradient over the overlay's own box, so it stops being a scrim when
    the overlay grows.** At rest the caption sits in the bottom fifth, where the gradient is
    strongest. Expanded, the panel is most of the screen tall and the same gradient is stretched
    over 700px, putting the title in the transparent part of it — over gold leaf, on the triptych
    where this was seen. `.overlay:has(.facts.expanded)` strengthens it. Anything that changes how
    tall the overlay can get has to think about this.
20. **The settings panel is constructed before `boot()` has loaded a locale.** Anything it draws
    at construction time renders with missing translations and logs a warning per string. The
    interval menu did exactly that until M13; it is now built on first open. A new list built in
    `createPanel`'s body rather than in `show()` will do it again.
21. **`speechSynthesis` has two traps and both are silent.** `getVoices()` returns `[]` on the
    first call in Chrome and fills in later, announced by `voiceschanged` — so asking for a Polish
    voice at page load gets the default one instead. And a long utterance is truncated in some
    builds; the text is split at sentence boundaries, which also makes `cancel()` take effect at
    the next boundary rather than after the whole thing. `frontend/js/speech.js`.
22. **Cleveland reports image dimensions as strings.** `"width": "900"`, not `900`. Carried
    through as integers by `_as_int`, because a scoring pass comparing a string to a number would
    be wrong without saying so. Its records also carry no `lqip`, no `alt_text` and no `color`,
    which is why the AI features are not offered on them at all — see ADR-0013.
23. **`clearTimeout` is not the same as stopping a clock.** `rotation.pause()` cleared its
    timers, and an `advance()` that was already in flight re-armed them on its way out in a
    `finally` — so the hold was silently lost. That window is about a second on every advance
    (fetching an artwork, decoding its image) and it is the *whole* window at page load. The
    result was that opening the settings panel, or expanding the details, did not always stop
    the picture changing underneath you — a promise `docs/product-spec.md` has made since M3.
    There is a `paused` flag now, and `arm()` respects it. Anything else that holds a
    self-rescheduling timer has the same shape of bug available to it.
24. **A personal email address found its way back into `.env.example`**, which M7 had removed on
    purpose, by way of a `git add -A` that swept up an unrelated working-tree edit. That file is
    what `docs/setup.md` step 3 tells you to copy, so a real address in it ships to everyone who
    clones this. Look at what `git add -A` is about to stage in a repository that has a committed
    template file in it.

25. **Two requests for the same thing do not come back in the order you asked.** Every facet
    click re-asks `/api/filters`, nothing sequenced them, and an exclusion is a NOT over the
    whole facet table — about 50ms slower than the same query without one on this index. So the
    answer saying "excluded" could land *after* the answer to the click that cleared it, and the
    panel drew the stale one. A count of zero on a row whose state had just gone back to `off`
    is exactly the pair `buildRow` disables: the facet went dead and there was no way to click
    it on again. `loadFilters` numbers its requests and drops any answer that is not the newest.
    Flow 7 could not see this — its `expect()` between clicks waits for each answer, so two are
    never in flight — and neither could a route handler that sleeps, which stops pytest issuing
    the second click as well. The delay has to happen inside the page. `frontend/js/panel.js`.
26. **A control offered a state its source could not honour.** The tri-state facet control was
    the same control on Cleveland, where exclusion is a NOT over a facet layer that does not
    exist: the third click produced a value the server rejected, `applySelection` dropped it on
    the next redraw, and the row snapped back to off. Whether a group can exclude is now set
    from the source before its options are, and the hint above the groups says which cycle is
    running. ADR-0013, ADR-0014.
27. **A dev server left running from an earlier session serves the code it started with.**
    Started without `--reload`, `uvicorn` on port 8000 answered every request with a pre-M13
    `PreferencesResponse` — `artwork_type` as a `str`, so every save 422'd and every read fell
    through to the defaults. It looks exactly like a frontend that has stopped persisting
    anything. Check what is actually listening before believing a bug: the stale process here
    was six hours old and the port was busy, so a fresh `uvicorn` never bound at all.

28. **A stored `false` cannot tell "no" from "never asked".** Every save writes every field, so
    `ambient: false` in `preferences` means nothing about whether the user has considered
    ambient mode. Fullscreen turns ambient on (M17), and the only way it can do that without
    overruling somebody who deliberately turned it off is a second field recording that the
    toggle was operated by hand: `ambient_by_hand`. Nothing in the UI shows it. Any future
    "turn this on for them" rule over a boolean preference has the same problem available to it.
29. **The Fullscreen API cannot be exercised through Chrome automation here.** Both a CDP
    keypress and a CDP click on a real button get `TypeError: not granted`, whatever
    `document.fullscreenEnabled` says. Headed Playwright does it properly, and headed is also
    the only way to see a wake lock actually acquired — the request is refused while the
    document is hidden, and a backgrounded or headless window is hidden. That is why the
    fullscreen rule was verified with a throwaway headed script rather than by eye or by a
    tenth flow.

30. **A default exclusion opens a filter group, and a test that clicks the summary closes it.**
    `syncCount()` opens a group as soon as anything in it is set, so seeding `type.coin`
    (M17) made the artwork-type group arrive already open — and two Playwright flows that
    began with `summary.click()` were toggling it shut and then failing on an invisible
    facet. A third failed on the badge reading "2 out" instead of "1". Both are the same
    lesson: a flow that starts from "a fresh install" starts from whatever the product
    defaults are that week. `open_group()` and `clear_filters()` in `tests/test_e2e.py`
    make the starting state explicit rather than assumed.

## Outstanding, and only the owner can close it

*(The first of these is closed. Kept below, struck through, because the way it was closed is
worth knowing.)*

~~**Publish the export, and put its `sha256` in the release notes.**~~ **Done, 2026-09-04.**
Release `v0.3.0` carries `vitrine-index.sqlite`, and the fetch line in `README.md` and
`docs/setup.md` is now a command rather than a shape:

    892404cbb2cd6f8290ad9ab3ca8ceea481ee1b59f48f96073a1d99659eff65be

**`--url` ran for real for the first time, and worked**: HTTPS, GitHub's 302 to its asset CDN
followed, 57.8MB in thirteen seconds, digest verified, 57,607 artworks merged. Until then it had
only ever been exercised against its own refusal paths.

Two things that went wrong on the way, neither of them in the code. The export in `dist/` was
**stale** — built before migrations 010 and 011, so its `schema_migrations` claimed schema 009 —
and `merge_corpus` only refuses an export *ahead* of the fetcher, so a stale one merges quietly
while misreporting itself. Re-run `export_index.py --force` before publishing, every time. And
the fetch command pasted into both docs arrived as a **markdown link** with the `--sha256` flag
name replaced by the digest; it is a long command with a URL in it, so check it is still a
command after pasting.

**`uv run pytest -m live` with a real key.** Neither provider has ever been called with a working
key. It is the only thing that can catch a wrong default model id, or `max_completion_tokens`
being wrong for the model in use. A fake key was pushed through the whole path in a browser and
came back a clean 401 — which proves the wiring and nothing about the model ids.

**This matters more after M14 than it did before.** The accessibility description runs on the same
provider and the same unverified `DEFAULT_MODEL`, and it rests on an assumption no mock can test:
that the prompt's restraint rules actually hold — that a one-clause `alt_text` produces two honest
sentences rather than a fluent invented paragraph. ADR-0015 says so explicitly. Check that first,
on a thin alt text, in both languages. While there, `client.messages.count_tokens` will confirm or
replace the character-derived token estimates in `docs/ai-system.md`, which is one call.

## Conventions worth matching

- `CLAUDE.md` is the contract; `app/`, `frontend/` and `tests/` each have their own.
- Fix the doc in the same commit as the code when reality disagrees with it.
- Commit messages say *why*, and name what was found rather than just what changed.
- Fixtures are recorded real responses in `tests/fixtures/aic/`, never hand-written.
- Definition of done includes opening it in a browser and looking at it. Every rendering bug in
  the list above was invisible to a passing test suite.
