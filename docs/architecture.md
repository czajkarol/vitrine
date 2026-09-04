# Architecture

## Layers

```
frontend/            static assets, no build step
    │  fetch()
app/api/             FastAPI routers, middleware, error shapes. HTTP in, HTTP out. No logic.
    │
app/services/        Orchestration. Rotation, selection, interpretation, index building.
    │
app/domain/          Models and pure logic: scoring, filtering, cache keys, counters. No I/O.
    │
app/providers/       Outbound: AIC client, AI provider implementations.
app/repositories/    SQLite persistence, and the OS keyring when there is one.
```

Rules that matter more than the diagram:

- **`domain/` imports nothing outward.** No `httpx`, no `sqlite3`, no `fastapi`. If you need to
  import one of those into `domain/`, the logic is in the wrong layer. This is the boundary that
  makes the scoring and cache-key logic testable without mocks.
- **Only `providers/aic/` knows AIC's JSON shape.** It parses into domain models and everything
  downstream sees only those. When AIC changes a field name, exactly one module changes.
- **Only `providers/ai/` names an AI vendor.** No `if provider == "openai"` outside that package.
- **Editorial judgement lives in `domain/vocabulary.py` and nowhere else.** Which of AIC's terms
  are the same thing, and which are not terms at all, is a product decision — pure, testable and
  in one file, so changing it is an edit and a `--retag` rather than an archaeology exercise.
- **Config is constructed once and injected.** No module reads `os.environ` at call time.
  A bring-your-own API key is the one piece of configuration that arrives after startup, and it
  goes through `repositories/credentials.py` and `services/ai_credentials.py` rather than around
  this rule: `Settings` stays immutable and the service swaps the live provider.

Do not add a layer to "be clean". A service that only forwards a call to a repository is noise;
let the router call the repository. Add the service when there is orchestration to do.

---

## The interfaces that actually matter

Three. Everything else can be a plain function.

```python
class ArtworkSource(Protocol):
    async def get(self, artwork_id: int) -> Artwork | None: ...
    async def search(self, spec: ArtworkQuery) -> list[Artwork]: ...

class InterpretationProvider(Protocol):
    name: str
    model: str
    async def interpret(self, req: InterpretationRequest) -> InterpretationResult: ...

class InterpretationCache(Protocol):
    async def get(self, key: CacheKey) -> Interpretation | None: ...
    async def put(self, key: CacheKey, value: Interpretation) -> None: ...
```

`InterpretationCache` has two implementations from day one: `SqliteCache` and `NullSharedCache`.
The second exists so the resolution chain is real code rather than a promise. See ADR-0004.

`interpret` returns an `InterpretationResult` — the interpretation plus the token usage the
provider reported — rather than a bare `Interpretation`, which is what this file said first.
It has to: the daily budget is enforced against `ai_usage`, and a provider that reports nothing
leaves that table empty and the cap unenforceable. `model` is on the Protocol for the same kind
of reason: it is part of the cache key, because the same provider on a different model does not
produce interchangeable text.

---

## Data flow: showing an artwork

```
GET /api/artwork/random
    → SelectionService
        → ArtworkIndexRepository.sample(pool)                 [SQLite, no network]
        → domain.selection.choose_next(candidates, history)   [pure]
        → HistoryRepository.push(id)
    → ArtworkResponse { id, title, artist, iiif_base, image_id, lqip, alt_text, …, source }
```

Three tiers, in order: the local index, then AIC, then the bundled fallback set. `source` on
the response says which one answered, so the UI can show a quiet offline indicator.

The index carries no IIIF base — that is a property of AIC's deployment, not of an artwork —
so the last one AIC reported is kept in `preferences` and reused. It is never hardcoded.

The frontend builds the IIIF URL itself from `iiif_base` and `image_id`, because only the browser
knows the viewport width and pixel ratio. The backend does not guess a width.

Selection reads from SQLite, not from AIC. That is the whole point of the index — it makes
"next artwork" instant and keeps us far under the 60 req/min ceiling.

---

## Persistence

One SQLite file, `data/vitrine.db`. Tables:

```
artwork_index        id, image_id, title, artist, date_display, medium_display,
                     credit_line, place_of_origin, department_title, artwork_type,
                     main_reference_number, description, width, height, is_boosted,
                     has_alt_text, alt_text, lqip, color_h, color_s, color_l,
                     score, indexed_at
artwork_terms        artwork_id, kind ('style' | 'subject'), value    — PK all three
artwork_facets       artwork_id, facet                                — PK both
artwork_feedback     artwork_id PK, kind ('like' | 'hide'), title, artist,
                     image_id, created_at
history              artwork_id, shown_at
interpretations      cache_key PK, artwork_id, language, provider, model,
                     prompt_version, payload_json, created_at
preferences          key, value
ai_usage             day, provider, requests, tokens_in, tokens_out
credentials          provider PK, api_key, updated_at
schema_migrations    name PK, applied_at
```

Five of those need a sentence each. Which of them may leave this machine, and which may
never, is [`docs/data.md`](data.md).

`artwork_type` is AIC's `artwork_type_title` — "Painting", "Coin" — and is the thing Explore
filters on and Curated scores. It was called `classification` until migration 002, which is a
name AIC also uses for something else entirely: `classification_title` on a Seurat reads "oil on
canvas". Renamed so nobody reaches for the wrong one.

`artwork_terms` holds style and subject, one row per value rather than a JSON array on
`artwork_index`, because Explore's real question is "how many artworks have subject X, for every
X" every time the panel opens. Against a join table that is an index lookup; against JSON it is a
full scan of 57,000 rows. Migration 007 has the working.

`artwork_facets` is the canonical filter layer over both of the above, artwork type included
as `type.*`. It exists so that filtering, excluding and counting are one query shape for all
three groups instead of a column special case plus a join table — which is what made exclusion
and dependent counts affordable at all. Derived and rebuildable: `build_index.py --retag` writes
it from the raw values in seconds with no network. ADR-0009.

`artwork_feedback` is likes and hides, one row per artwork so `kind` is a state rather than a
log. It carries a small snapshot — title, artist, `image_id` — and **no foreign key to
`artwork_index`**, because an artwork can be on screen without being indexed at all: the second
and third tiers serve straight from AIC and from the bundled set. A foreign key would turn
"like the artwork I am looking at" into an `IntegrityError` on exactly the setup a new user has.
Migration 009, ADR-0010.

`credentials` is the fallback tier for a bring-your-own API key, used only when the OS keyring is
unavailable, and it is unencrypted. It is the reason `data/vitrine.db` can never be published:
the same file holds a rebuildable cache and a secret. The publishable subset is the three corpus
tables, copied out by `repositories/corpus.py` — ADR-0011.

Enable WAL mode. Wrap access in repository classes; no raw SQL outside `repositories/`.
Migrations: a plain numbered-SQL-files runner is enough. Do not add Alembic for this.

`sqlite3` is synchronous and there is no async driver here on purpose. Repositories expose
a `*_sync` method and an `async` wrapper that pushes it onto a worker thread, so the request
path never blocks. Connections are opened per operation rather than shared, because a
`sqlite3` connection cannot be moved between threads.

`preferences` holds two kinds of thing: what the user chose, and what the app learned for
itself — the IIIF base AIC reported, and how far the crawler got. Only the first kind is
exposed over HTTP, through a typed schema rather than a key/value passthrough.

---

## The index

`scripts/build_index.py` is the reason the app works. It populates `artwork_index` by walking
`/artworks` — the plain listing endpoint, which is uncapped — at AIC's requested 1 req/s,
filtering to public-domain works with usable images, scoring them, and writing rows.

The nightly data dumps are not needed: the listing endpoint paginates the whole collection in
about 22 minutes. ADR-0003 assumed otherwise; see its postscript and `docs/aic-api.md`.

It is a script, run manually or on a schedule, never on the request path. The app degrades to
direct AIC queries if the index is empty, but that path is the fallback, not the design.

Make it resumable and idempotent. Re-running it must update rows, not duplicate them.

### Moving a corpus between databases

`scripts/export_index.py` and `scripts/fetch_index.py` are thin CLIs over
`repositories/corpus.py`, which holds the allow-list of corpus tables and the `ATTACH`-based
copy in both directions. Keeping the SQL in a repository rather than in the scripts is the
same rule as everywhere else, and it has a second payoff here: export and merge are two
halves of one round trip, and a shared allow-list is the only reason they cannot drift apart.

The export is *built up* from named tables into a fresh file, never *cut down* from a copy of
the live one. A deny-list would be wrong by default the moment somebody adds a table, and one
of the tables it would have to remember is `credentials`. ADR-0011.

---

## Frontend structure

ES modules, no bundler, served as static files by FastAPI.

```
frontend/
    index.html
    css/
    js/
        main.js         wiring, and the only place the pieces below know about each other
        display.js      the transition pipeline — the one genuinely tricky file
        rotation.js     timer, visibility handling, preload scheduling
        overlay.js      metadata, and the container the AI section renders into
        interpretation.js  the AI request, its states, and the labelled section itself
        panel.js        settings — named for what it is, not for what it holds
        i18n.js         locale loading, {placeholder} substitution, data-i18n in markup
        ambient.js      the Screen Wake Lock, and re-taking it when the tab comes back
        state.js        the plain object described below
        shortcuts.js    the keyboard map
        fullscreen.js
        api.js          the only file that calls fetch()
    locales/  en.json  pl.json
```

State lives in one module as a plain object with explicit setters. No global mutable sprawl,
no event-bus abstraction for six events.

---

## What is deliberately not here

No Docker, no Alembic, no Redis, no Celery, no dependency-injection framework, no repository
factory registry, no plugin loader. Every one of those would be defensible in a larger system
and is dead weight here. If one becomes necessary, write an ADR first.
