# Architecture

## Layers

```
frontend/            static assets, no build step
    │  fetch()
app/api/             FastAPI routers. HTTP shapes in, HTTP shapes out. No logic.
    │
app/services/        Orchestration. Rotation, selection, interpretation, index building.
    │
app/domain/          Models and pure logic: scoring, filtering, cache keys. No I/O.
    │
app/providers/       Outbound: AIC client, AI provider implementations.
app/repositories/    SQLite persistence.
```

Rules that matter more than the diagram:

- **`domain/` imports nothing outward.** No `httpx`, no `sqlite3`, no `fastapi`. If you need to
  import one of those into `domain/`, the logic is in the wrong layer. This is the boundary that
  makes the scoring and cache-key logic testable without mocks.
- **Only `providers/aic/` knows AIC's JSON shape.** It parses into domain models and everything
  downstream sees only those. When AIC changes a field name, exactly one module changes.
- **Only `providers/ai/` names an AI vendor.** No `if provider == "openai"` outside that package.
- **Config is constructed once and injected.** No module reads `os.environ` at call time.

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
    async def interpret(self, req: InterpretationRequest) -> Interpretation: ...

class InterpretationCache(Protocol):
    async def get(self, key: CacheKey) -> Interpretation | None: ...
    async def put(self, key: CacheKey, value: Interpretation) -> None: ...
```

`InterpretationCache` has two implementations from day one: `SqliteCache` and `NullSharedCache`.
The second exists so the resolution chain is real code rather than a promise. See ADR-0004.

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
                     credit_line, place_of_origin, department_title, classification,
                     main_reference_number, description, width, height, is_boosted,
                     has_alt_text, alt_text, lqip, color_h, color_s, color_l,
                     score, indexed_at
history              artwork_id, shown_at
interpretations      cache_key PK, artwork_id, language, provider, model,
                     prompt_version, payload_json, created_at
preferences          key, value
ai_usage             day, provider, requests, tokens_in, tokens_out
```

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
        overlay.js      metadata + AI panel
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
