# vitrine

An ambient digital-art display. One public-domain artwork from the Art Institute of Chicago at
a time, full-bleed on a dark background, rotating on a timer. Built for a second monitor.

![The display, with the metadata overlay pinned](docs/screenshots/display.jpg)

It runs on your own machine, serves an artwork from a local index in about 19ms without touching
the network, and keeps working when the museum's API does not. AI interpretation is optional,
off by default, and the app is complete without it.

## Quick start

```bash
uv sync --all-extras
cp .env.example .env          # set AIC_USER_AGENT to your project name and email
uv run python scripts/build_index.py --limit 5000
uv run uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. Press `F` for fullscreen and leave it.

Fuller instructions, including what each step buys you, are in [docs/setup.md](docs/setup.md).

The index step is optional but wanted: without it the app asks AIC for each artwork and falls
back to a bundled set of thirty when the API is unreachable. With it, selection is a local
SQLite query. If there is a published export, fetching it is the fast path and costs AIC
nothing:

```bash
uv run python scripts/fetch_index.py --url https://.../vitrine-index.sqlite --sha256 <digest>
```

Otherwise, a full walk of the collection is 1,328 requests at AIC's own etiquette of one
request per second — 22 minutes of request time, about 30 minutes measured end to end — and it
is resumable:

```bash
uv run python scripts/build_index.py             # everything, ~30 min
uv run python scripts/build_index.py --score-only # rescore what is already indexed
uv run python scripts/build_index.py --explain 27992
```

A full walk is the one operation that needs the owner's say-so before it starts. It is not
about AIC's rate limit, which it stays well inside; it is about half an hour of automated
traffic to someone else's service.

## Keyboard

```
Space      next artwork
F          fullscreen
I          metadata overlay — and, if AI is configured, an interpretation
L          add to favourites, or remove
X          hide this artwork — never show it again, in any mode
1 2 3 4 5  rotation interval: 30 sec / 1 / 5 / 15 / 30 min
S          toggle settings
Esc        close settings, else close the overlay, else leave fullscreen
```

## Settings

![The settings panel](docs/screenshots/settings.jpg)

Mode, rotation interval, artwork type, style, subject, ambient mode, language, and the AI key.
Opening the panel pauses the rotation; closing it starts the clock again. Everything is saved
locally and survives a reload.

**Explore and Curated.** Explore filters by artwork type, style and subject, offering only the
values the index can actually sustain — a filter with four artworks behind it is worse than no
filter, so it is not shown. The options are our own vocabulary rather than the museum's
cataloguing ([ADR-0009](docs/adr/0009-canonical-facets.md)): `portrait` and `portraits` are one
option with one honest count, and provenance terms like "Collected by Hugh Edwards" are not
offered as subjects at all. Each group also has a collapsed **Exclude** list, which is
multi-valued where inclusion is not, and every count is what choosing it would actually yield
under the rest of your selection. Curated
ranks by a transparent weighted score over six signals: AIC's own `is_boosted`
curatorial flag, weighted highest because it is the only one carrying a human judgement about
the work; resolution; aspect ratio; how complete the caption will be; whether the museum wrote a
visual description; and whether the object is the kind of thing that fills a frame — a painting
rather than a chair. The weights are one dict with a comment each, and `--explain` prints the
breakdown for any artwork. It ranks rather than excludes, so with nothing scored yet you get a
rotation instead of a blank screen.

**Favourites, and "For you".** `L` likes what is on screen, `X` hides it for good. Once there
are five favourites, a third mode ranks by what they have in common — frequency over the
canonical facets, multiplied into the curated score so quality still bounds it. Below five it
falls back to Curated and says so, because a recommendation that is not one is worse than no
recommendation. Explicit gestures only: no dwell time, no skips, nothing inferred from silence
([ADR-0010](docs/adr/0010-personalisation-from-explicit-feedback.md)).

**English and Polish**, switchable without a reload.

**Ambient mode** holds a Screen Wake Lock, and re-acquires it when the tab becomes visible again,
because the browser takes the lock away whenever you look elsewhere. Off by default: keeping
someone's screen awake is a side effect on their machine.

## AI interpretation

Optional, off by default, and never on the critical path. Pinning the overlay with `I` asks for
an interpretation of what is on screen: a visual description, a reading, a few themes, and one
thing to look closer at. It is labelled as generated, in its own container, and never shares one
with the museum's own text.

Generation happens **on demand only, never on rotation**. That single decision is worth an order
of magnitude in cost, because most artworks are shown and never asked about.

Around the call: a local SQLite cache keyed on artwork, language, provider, model and prompt
version; a hard cap on output tokens and a daily request cap enforced *before* the call; a
circuit breaker that stops calling a provider that keeps failing and still serves from cache; and
a short timeout, because an interpretation that arrives after the artwork has rotated away is not
wanted.

Two providers are implemented, Anthropic and OpenAI, behind one interface. Nothing outside
`app/providers/ai/` names a vendor.

### Bringing your own API key

Press `S`, pick Anthropic or OpenAI, paste your key. It takes effect immediately — no restart.
`.env` also works (`AI_ENABLED`, `AI_PROVIDER`, and the matching key); a key saved from the panel
takes precedence over one in the file.

**Where the key is kept, and how safe that is.** If the `keyring` package is installed and your
machine has a working credential store, the key goes there:

```bash
uv sync --extra keyring        # or: pip install "vitrine[keyring]"
```

Otherwise it goes in `data/vitrine.db`, **unencrypted**. Anyone who can read that file can read
your key. The settings panel says which of the two is in use before you type anything. This is a
local-first app ([ADR-0002](docs/adr/0002-local-first-single-user.md)) and the database is a file
you own, but it is worth knowing, and it is worth installing the extra.

The key is never sent to the browser, never written to a log, and never returned by an endpoint.
Everything that reports on it shows at most its last four characters. Remove it with the button
in the same panel.

## Architecture

```
frontend/            static assets, no build step
    │  fetch()
app/api/             FastAPI routers, middleware, error shapes. HTTP in, HTTP out
    │
app/services/        orchestration: selection, interpretation, credentials
    │
app/domain/          models and pure logic: scoring, cache keys, counters. No I/O
    │
app/providers/       outbound: the AIC client, the AI providers
app/repositories/    SQLite, and the OS keyring when there is one
```

The dependency direction is one-way and enforced where it can be: `ruff` bans `httpx` outside
`app/providers/`, `domain/` imports nothing outward, and only the AIC client knows AIC's JSON
shape. `docs/architecture.md` has the rules; `docs/adr/` has the reasoning.

**Three tiers for an artwork.** Local index, then AIC, then a bundled set of thirty. The first
answers without a network, which is the whole point of [ADR-0003](docs/adr/0003-local-artwork-index.md);
the last means a fresh clone with no index and no connection still shows something.

**Rate limited, on the two routes whose cost leaves the machine.** Burst 10, one token back
every 3 seconds, and a rolling ceiling of 400 an hour — `RATE_LIMIT_*` in `.env`, and
`RATE_LIMIT_BURST=0` turns it off. Not about AIC's 60 requests a minute, which the local index
keeps us far below; about not leaning on a CDN and about bounding a tab that got stuck
overnight. The unit is an *advance* rather than a request, because showing one artwork is two
of them. Over the limit is a `429` with `Retry-After`, and the display waits out exactly that
long rather than retrying on its own schedule.

**Two paths for an image.** Direct from AIC's IIIF service first, and if that fails, once,
through `GET /api/image/{image_id}`. AIC's images sit behind Cloudflare, which needs a request
header an `<img>` tag cannot send — measured, in a browser, and written up in
[ADR-0008](docs/adr/0008-image-delivery-fallback.md). The outcome is remembered for the session
so the failed round trip is paid once rather than every rotation.

## Endpoints

| | |
|---|---|
| `GET /api/artwork/random` | one artwork, from whichever tier answers — rate limited |
| `GET /api/image/{image_id}` | the IIIF fallback — allow-listed widths, id format checked, rate limited |
| `GET /api/filters` | the facet vocabulary, with counts dependent on the current selection |
| `GET`/`PUT /api/preferences` | the settings panel's state |
| `GET /api/interpretation/{id}` | one interpretation, on demand |
| `GET`/`PUT`/`DELETE /api/ai/key` | the bring-your-own key, never returned |
| `GET`/`PUT`/`DELETE /api/favorites` | likes and hides, with a snapshot that outlives the index |
| `GET /api/scoring` | the curated weights, read from the code so the UI cannot drift |
| `GET /api/health` | liveness, and whether AI is available |
| `GET /api/stats` | cache hit ratio, provider latency, AIC error rate, today's spend |

## Testing

```bash
uv run pytest                 # 539 tests: unit, contract, integration. No network
uv run pytest -m live         # 9, against the real AIC API and a real AI provider if keyed
uv run pytest -m e2e          # 6 Playwright flows; it starts its own server
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

CI runs the default selection plus `ruff` and `mypy`, and never runs `live` or `e2e`.

Fixtures are recorded AIC responses, not hand-written dicts: a hand-written fixture tests your
idea of the API, which is the precise thing a contract test exists to check. `docs/testing.md`
lists the failure paths that each have a named test — a 500 that succeeds on retry, an image that
404s at display time, a corrupt cache row, an exhausted budget, an open circuit.

## Security and privacy

- No API key ever reaches the frontend. All AI calls go through the backend.
- Keys are redacted to their last four characters in logs, errors and responses, and every log
  record additionally passes through a redaction pass that catches a key-shaped token wherever it
  came from.
- `.env` is gitignored. The bring-your-own key goes in the OS keyring where there is one.
- Binds to localhost and serves one user ([ADR-0002](docs/adr/0002-local-first-single-user.md)).
  There is no login, because there is nobody else.
- **`data/vitrine.db` is never committed or published.** Where there is no OS keyring it holds
  the API key in plain text, in the same file as the index. `scripts/export_index.py` builds a
  publishable copy from an allow-list of corpus tables rather than by deleting from that one
  ([ADR-0011](docs/adr/0011-distribute-the-index-as-a-release-asset.md), [docs/data.md](docs/data.md)).
- The image endpoint is not a general-purpose proxy: it validates the image id against a UUID
  shape and the width against the five cached IIIF widths.

## Limitations

- **The index goes stale.** AIC can unpublish or replace any image at any time, so it is treated
  as a cache: a dead image at display time skips to the next artwork rather than stopping.
- **The facet vocabulary is an editorial map, and AIC's own vocabulary drifts.** Merging and
  dropping is written down one value at a time in `app/domain/vocabulary.py`, so it stays
  correct only as long as someone maintains it. `build_index.py --retag` rebuilds the whole
  layer in under two seconds with no network, and reports how many raw values it dropped — a
  change in that number is the signal that the map has fallen behind.
- **Interpretations do not stream.** The panel waits for the whole answer. SSE is described in
  `docs/ai-system.md` as a refinement, not a foundation.
- **No shared cache.** Deliberately an interface and nothing else
  ([ADR-0004](docs/adr/0004-defer-shared-cache.md)).
- **Cloudflare's behaviour towards IIIF hotlinking was measured on one network on one day.** It
  may differ elsewhere, and may change without notice. The fallback handles both worlds; a `live`
  test asserts which one we are in.

## Documentation

| | |
|---|---|
| `docs/setup.md` | From a clean clone to a picture on screen, and what to do when it does not work |
| `docs/data.md` | What is stored, what is rebuildable, what may be published |
| `docs/product-spec.md` | What the app does and how it behaves |
| `docs/architecture.md` | Layers, boundaries, data flow |
| `docs/aic-api.md` | AIC API constraints, fields, licensing |
| `docs/ai-system.md` | Providers, caching, prompts, cost control |
| `docs/testing.md` | Test strategy |
| `docs/adr/` | Why things are the way they are |
| `HANDOFF.md` | The state of play, for whoever picks this up next |

## Attribution

Artwork data and images come from the Art Institute of Chicago's public API. Collection data is
CC0; the `description` field is CC BY 4.0, and the overlay credits the Art Institute whenever a
description is shown. See <https://www.artic.edu/terms>.

Only works flagged `is_public_domain` are ever displayed. That is a hard filter at index time and
at display time, not a preference — [ADR-0007](docs/adr/0007-public-domain-only.md).

## How this was built

Implementation was done by Claude Code working autonomously against the specification in
`CLAUDE.md` and `docs/`, with me as reviewer and product owner. The architectural decisions, and
the reasoning behind them, are recorded in `docs/adr/` — including the two that were reversed or
corrected in flight, which are the interesting ones.
