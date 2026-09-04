# vitrine

An ambient digital-art display. One public-domain artwork at a time — from the Art Institute of
Chicago, or the Cleveland Museum of Art — full-bleed on a warm dark ground, rotating on a timer.

![The display, with the metadata overlay pinned](docs/screenshots/display.jpg)

It runs on your own machine, serves an Art Institute artwork from a local index in about 19ms
without touching the network, and keeps working when the museum's API does not. The AI features
are optional, off by default, and the app is complete without them.

## Quick start

```bash
uv sync --all-extras
cp .env.example .env          # set AIC_USER_AGENT to your project name and email
uv run python scripts/build_index.py --limit 5000
uv run python scripts/run.py
```

The last line serves the app and opens <http://127.0.0.1:8000> once it answers. Press `F` for
fullscreen and leave it. `uv run uvicorn app.main:app --reload` is the same server without the
browser step — uvicorn starts, prints the URL and waits, which is worth knowing because a
successful start looks exactly like a hang.

Fuller instructions, including what each step buys you, are in [docs/setup.md](docs/setup.md).

The index step is optional but wanted: without it the app asks AIC for each artwork and falls
back to a bundled set of thirty when the API is unreachable. With it, selection is a local
SQLite query. If there is a published export, fetching it is the fast path and costs AIC
nothing:

```bash
uv run python scripts/fetch_index.py \
  --url https://github.com/czajkarol/vitrine/releases/download/v0.3.0/vitrine-index.sqlite \
  --sha256 892404cbb2cd6f8290ad9ab3ca8ceea481ee1b59f48f96073a1d99659eff65be
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
← →        back and forward through what you have seen
F          fullscreen
I          metadata overlay — and, if AI is configured, an interpretation
H          keep this artwork up five minutes longer (press again for more, up to an hour)
A          describe this artwork aloud, for listening
L          add to favourites, or remove
D          show me less like this, or take it back
X          hide this artwork — never show it again, in any mode
1 2 3 4 5  rotation interval: 30 sec / 1 / 5 / 15 / 30 min
S          toggle settings
?          this list, in the settings panel
Esc        close settings, else close the overlay, else leave fullscreen
```

And one mouse gesture: **a left click on the artwork** takes the overlay away entirely, and
moving the mouse does not bring it back. Click again to restore it. It says nothing when it does
— the way back is the click you just made.

The same list lives in the app, translated, behind `?` — a shortcut documented only in a README
is a shortcut nobody knows about.

## Settings

![The settings panel](docs/screenshots/settings.jpg)

Source, mode, rotation interval, filters, ambient mode, language, the AI key, and the keyboard
map. Opening the panel pauses the rotation; closing it starts the clock again. Everything is
saved locally and survives a reload.

**Two museums.** The Art Institute is the indexed one and everything below applies to it.
Cleveland is fetched live, one request per artwork, and is deliberately smaller: Random only and
one filter. Curated and "For you" rank against a score only the local index carries, so they are
disabled while Cleveland is selected and the panel says why. Cleveland's records carry no blur
placeholder, no dominant colour and no visual description, so the crossfade, the scrim and the AI
features degrade in defined ways rather than silently
([ADR-0013](docs/adr/0013-cleveland-as-a-live-source.md)).

**Explore and Curated.** Explore filters by artwork type, style and subject, offering only the
values the index can actually sustain — a filter with four artworks behind it is worse than no
filter, so it is not shown. The options are our own vocabulary rather than the museum's
cataloguing ([ADR-0009](docs/adr/0009-canonical-facets.md)): `portrait` and `portraits` are one
option with one honest count, and provenance terms like "Collected by Hugh Edwards" are not
offered as subjects at all.

Each facet has one control with three states: click to include, again to exclude, again to
clear. Several values inside a group combine with **OR** — painting *or* print — and the groups
combine with AND, so "a Japanese print" narrows the way you expect
([ADR-0014](docs/adr/0014-multi-select-filters.md)). Every count is what choosing that option
would actually yield under the rest of your selection. Curated
ranks by a transparent weighted score over six signals: AIC's own `is_boosted`
curatorial flag, weighted highest because it is the only one carrying a human judgement about
the work; resolution; aspect ratio; how complete the caption will be; whether the museum wrote a
visual description; and whether the object is the kind of thing that fills a frame — a painting
rather than a chair. The weights are one dict with a comment each, and `--explain` prints the
breakdown for any artwork. It ranks rather than excludes, so with nothing scored yet you get a
rotation instead of a blank screen.

**Favourites, and "For you".** `L` likes what is on screen, `D` asks for less like it, `X` hides
it for good. The middle one is a ranking signal and nothing else — the artwork keeps coming
round, which is what `X` is for and `D` is not. Once there are five favourites, a third mode
ranks by what they have in common — frequency over the canonical facets, multiplied into the
curated score so quality still bounds it. Below five it falls back to Curated and says so,
because a recommendation that is not one is worse than no recommendation. Explicit gestures
only: no dwell time, no skips, nothing inferred from silence
([ADR-0010](docs/adr/0010-personalisation-from-explicit-feedback.md)).

**Going back.** `←` and `→` walk the last twenty artworks the display has shown. It keeps the
records rather than the decoded images, and asks the browser's cache for the picture on the way
back, so going back is normally instant and costs no request.

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
`app/providers/ai/` names a vendor — including "Anthropic only" for the spoken descriptions
below, which is a second capability Protocol a provider either satisfies or does not, rather
than a name compared somewhere.

`docs/ai-system.md` has what this actually costs, measured: under half a cent per interpretation
or description at the default model, and the 200-a-day cap is under $1.50 even fully spent.

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

## Described for listening

`A` asks for a spoken description of the artwork on screen and reads it aloud. It is for people
who cannot see the screen, and it is the one feature here where a wrong sentence would not be
recoverable — everywhere else the artwork is there, disagreeing with it.

So the design is built around one constraint, and the app says it out loud on every screen that
shows a description: **no AI has seen the artwork.** The words come from the Art Institute's own
`thumbnail.alt_text`, written by a person who did look at it and present on all 57,607 indexed
works, expanded and rearranged into something meant to be heard. The prompt's strongest rules are
to take everything visual from there and to *match the length of the source*, because padding a
one-clause description is inventing and a listener cannot tell the difference. An artwork with no
visual metadata at all is refused rather than described.
([ADR-0015](docs/adr/0015-accessibility-descriptions.md).)

Playback uses the browser's own speech synthesis: no key, no per-word charge, and it works
offline. Replaying costs nothing — the text is on screen and the answer is cached — so it is its
own control rather than a second request. Asking for a description also holds the rotation at
five minutes or slower for the rest of the session, without changing the interval you chose,
because a description takes most of a minute to hear.

Anthropic only for now. The feature is offered only where the configured provider can actually
produce one; a control that is offered and then refuses is worse than one that is not offered.


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
app/providers/       outbound: the two museum clients, the AI providers
app/repositories/    SQLite, and the OS keyring when there is one
```

The dependency direction is one-way and enforced where it can be: `ruff` bans `httpx` outside
`app/providers/`, `domain/` imports nothing outward, and each museum's JSON shape is known to
exactly one module. `docs/architecture.md` has the rules; `docs/adr/` has the reasoning.

**Three tiers for an Art Institute artwork.** Local index, then AIC, then a bundled set of
thirty. The first answers without a network, which is the whole point of
[ADR-0003](docs/adr/0003-local-artwork-index.md); the last means a fresh clone with no index and
no connection still shows something.

**One tier for a Cleveland artwork.** It is a live source with nothing under it, and when it
cannot answer the display keeps what is on screen rather than quietly showing an Art Institute
work instead — the user picked a museum
([ADR-0013](docs/adr/0013-cleveland-as-a-live-source.md)).

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
| `GET /api/access-description/{id}` | one spoken visual description, on demand |
| `GET`/`PUT`/`DELETE /api/ai/key` | the bring-your-own key, never returned |
| `GET`/`PUT`/`DELETE /api/favorites` | likes, dislikes and hides, with a snapshot that outlives the index |
| `GET /api/scoring` | the curated weights, read from the code so the UI cannot drift |
| `GET /api/health` | liveness, and whether AI is available |
| `GET /api/stats` | cache hit ratio, provider latency, AIC error rate, today's spend |

## Testing

```bash
uv run pytest                 # 609 tests: unit, contract, integration. No network
uv run pytest -m live         # 9, against the real AIC API and a real AI provider if keyed
uv run pytest -m e2e          # 9 Playwright flows; they start their own servers
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
- **Spoken descriptions are written from the museum's text, not from the image.** That is a
  deliberate design constraint rather than an oversight, and its cost is real: where the Art
  Institute's alt text is one short clause, the description will be short too. A vision model
  reading the actual image would be better and would need a weaker claim about where the words
  came from — [ADR-0015](docs/adr/0015-accessibility-descriptions.md) says what would make us
  revisit it.
- **Cleveland is display-only.** No local index, so no Curated, no "For you", no style or subject
  filters, and no AI. One request per artwork, so it depends on the network in a way the Art
  Institute does not.
- **No provider has ever been called with a real key.** The whole AI path is proven against a
  mock and against a deliberate 401. The default model id is unverified.
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
| `docs/ai-system.md` | Providers, caching, prompts, cost control, and what it actually costs |
| `docs/testing.md` | Test strategy |
| `docs/adr/` | Why things are the way they are |
| `HANDOFF.md` | The state of play, for whoever picks this up next |

## Attribution

Artwork data and images come from the Art Institute of Chicago's public API. Collection data is
CC0; the `description` field is CC BY 4.0, and the overlay credits the Art Institute whenever a
description is shown. See <https://www.artic.edu/terms>.

Cleveland artworks come from the Cleveland Museum of Art's Open Access API, and only records
flagged `share_license_status: "CC0"` are used. The overlay credits Cleveland on its own
artworks; attribution is per artwork rather than per app, because it is a licence condition
rather than a label. See <https://openaccess-api.clevelandart.org/>.

Only works flagged `is_public_domain` (or CC0 at Cleveland) are ever displayed. That is a hard
filter at fetch time and at display time, not a preference —
[ADR-0007](docs/adr/0007-public-domain-only.md).

## How this was built

Implementation was done by Claude Code working autonomously against the specification in
`CLAUDE.md` and `docs/`, with me as reviewer and product owner. The architectural decisions, and
the reasoning behind them, are recorded in `docs/adr/` — including the two that were reversed or
corrected in flight, which are the interesting ones.
