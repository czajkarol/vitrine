# Testing

The suite has one job that matters more than coverage: catching the two things that actually
break this app, which are AIC changing its response shape and the display pipeline mishandling
a bad image.

## Layers

**Unit** — everything in `domain/`. Scoring, cache keys, filter construction, history penalties,
interval maths. These are pure functions and need no mocks. If a unit test needs a mock, the
logic under test has I/O in it and belongs elsewhere.

**Contract** — the AIC client against recorded responses. Fixtures in `tests/fixtures/aic/` are
real responses captured from the live API and committed. `respx` intercepts httpx so nothing
leaves the machine. These tests are what tell you AIC renamed a field.

**Integration** — API routes with a real temporary SQLite database, repositories, the AI
interpretation chain against `MockProvider`. Fast, no network.

**Live** — a handful of tests marked `@pytest.mark.live` that hit the real AIC API. Excluded
from the default run and from CI. Run them by hand when a contract test starts looking suspicious
or before a release. They are also how fixtures get refreshed.

**E2E** — Playwright, nine flows, no more:

1. App loads and an image appears
2. Space advances to a different artwork
3. `I` opens the metadata overlay
4. Language switches to Polish and back
5. With AI disabled, the overlay shows museum data and no error
6. `L` adds a favourite and it survives a reload
7. A facet clicked twice excludes it, and the display stops serving that type
8. The spoken description reaches the screen with its grounding line
9. The rotation is actually held while somebody is reading

Playwright is slow and flaky in proportion to how much you ask of it. Everything not in that
list belongs in a unit or integration test.

**A new flow has to argue for its slot**, and the last four each did. The argument is the same
one every time: **there is no frontend test runner here and there will not be** (ADR-0005), so a
rule that only exists in the browser is either an e2e flow or it is untested.

- The **sixth** (M11) is the one feature that crosses every layer in a way no smaller test can:
  a keypress, an HTTP write, a SQLite row with no foreign key behind it, and the state read back
  onto a fresh page. Each half has a unit test; only this proves they meet.
- The **seventh** (M13) is the only check that a facet control cycles through three states and
  that the third one narrows what is served. That control is the panel's largest surface and was
  rewritten wholesale, and the states exist nowhere but in the browser. It earned its place
  immediately: on its first run it found that the artwork-type group is called `artwork-type`
  while its facets are `type.*`, and that code matching the shared exclusion list on the group's
  own name silently dropped every exclusion in that group.
- The **eighth** (M14) covers the one feature whose failure the person it is for cannot see. A
  sighted user notices an empty panel; somebody relying on the spoken description notices
  silence, which is indistinguishable from having pressed the wrong key. So it asserts the three
  things that make it usable: the region appears, the text arrives, and the line saying where the
  words came from is on screen with it.
- The **ninth** (M16) covers a promise made in M3 — opening the settings pauses the rotation —
  that broke silently and that 587 unit tests and eight flows all missed. `pause()` cleared the
  timers, which is not the same as stopping the clock: an `advance()` already in flight re-armed
  on its way out. **It is the only slow flow, and deliberately so**: it waits out a real
  thirty-second interval, because the bug is that a clock keeps ticking when told not to and
  nothing shorter can observe that. It moves the mouse while it waits, because a still mouse
  fades the overlay and correctly *releases* the hold — testing that path would be testing the
  opposite feature.

The fixture starts its own uvicorn on a free port, against a temporary database seeded from the
bundled fallback set, and strips `AI_*` and every vendor key out of the environment it inherits —
a key in the developer's shell would turn AI on and flow 5 would silently stop testing what it
says it tests. Metadata therefore needs no AIC call; the images still come from artic.edu, which
is the one thing in the suite that touches the network and is exactly what flow 1 checks.

**Two things these flows needed, and both are worth knowing.** The seeded index is padded
with copies of the bundled records under synthetic ids *and synthetic titles*, because a facet is
not offered below forty artworks and the bundled set is thirty — and because copies sharing a
title with their original made a rotation indistinguishable from no rotation, which is exactly
what flow 9 asserts about — without it the panel correctly reports that there
is nothing worth filtering on and flow 7 has nothing to click. That is the narrowest departure
from "fixtures are recorded, not invented" that makes the flow possible, and what is under test
is the panel rather than AIC's shape. And flow 8 runs against a **second server** with
`AI_PROVIDER=mock`, because flow 5 asserts the exact opposite — that with nothing configured the
feature is not offered — and one process changing its mind halfway through the module would make
one of the two a lie.

Wait on `naturalWidth`, never on `load` or `complete`: an `<img>` with no src at all reports
complete, and so does one whose src has already 404'd.

```bash
uv sync --all-extras
uv run playwright install chromium
```

## Failure paths

Each of these has a named test. They are the ones that matter, because they are what a user
running the app for eight hours will actually hit:

- Liking an artwork the index has never seen — the ordinary case on a fresh clone
- A hidden artwork never coming back, in any mode; a *disliked* one still coming round
- The same artwork id at two museums being two separate verdicts
- "For you" with too few likes to personalise, saying so rather than pretending
- A live source that is down, failing without falling through to the Art Institute
- A live source whose filter list cannot be fetched, coming back empty rather than 500
- An artwork with no alt text and no description being refused a spoken description, before
  any provider call is made
- A provider that cannot write a spoken description saying so, rather than failing
- AIC returns 500, then succeeds on retry
- AIC times out
- AIC returns valid JSON with `image_id: null`
- An IIIF image 404s at display time
- `img.decode()` rejects
- The local index is empty
- The interpretation cache row is corrupt
- The AI provider returns unparseable JSON
- The AI daily budget is exhausted
- The circuit breaker is open

## Conventions

- `pytest-asyncio` in auto mode.
- Markers registered in `pyproject.toml`: `live`, `e2e`. Default run excludes both.
- Scoring tests assert ordering, never exact floats — otherwise tuning a weight breaks the suite
  and the suite gets tuned instead of the weights.
- No test asserts that a mock was called unless the call itself is the behaviour under test.
- Fixtures are recorded, not invented. A hand-written AIC fixture encodes your assumption about
  the API, which is the precise thing the contract test is supposed to check.

## Running

```bash
uv run pytest                     # unit + contract + integration
uv run pytest -m live             # real AIC, manual
uv run pytest -m e2e              # Playwright; it starts its own server
uv run pytest --cov=app           # coverage when you want a number
```

CI runs the default selection plus `ruff` and `mypy`. It never runs `live` or `e2e`.
