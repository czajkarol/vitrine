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
GET /api/artwork/next?mode=curated&filters=…
    → RotationService
        → ArtworkIndexRepository.sample(filters, history)     [SQLite, no network]
        → AicClient.get(id)                                    [network, for fresh detail]
        → HistoryRepository.push(id)
    → ArtworkResponse { id, title, artist, iiif_base, image_id, lqip, alt_text, dimensions }
```

The frontend builds the IIIF URL itself from `iiif_base` and `image_id`, because only the browser
knows the viewport width and pixel ratio. The backend does not guess a width.

Selection reads from SQLite, not from AIC. That is the whole point of the index — it makes
"next artwork" instant and keeps us far under the 60 req/min ceiling.

---

## Persistence

One SQLite file, `data/vitrine.db`. Tables:

```
artwork_index        id, image_id, title, artist, date_display, classification,
                     style_ids, width, height, is_boosted, has_alt_text, lqip,
                     score, indexed_at
history              artwork_id, shown_at
interpretations      cache_key PK, artwork_id, language, provider, model,
                     prompt_version, payload_json, created_at
preferences          key, value
ai_usage             day, provider, requests, tokens_in, tokens_out
```

Enable WAL mode. Wrap access in repository classes; no raw SQL outside `repositories/`.
Migrations: a plain numbered-SQL-files runner is enough. Do not add Alembic for this.

---

## The index

`scripts/build_index.py` is the reason the app works. It populates `artwork_index` by walking
AIC — respecting the 1 req/s scraping etiquette — or by reading a downloaded data dump, filtering
to public-domain works with usable images, scoring them, and writing rows.

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
        display.js      the transition pipeline — the one genuinely tricky file
        rotation.js     timer, visibility handling, preload scheduling
        overlay.js      metadata + AI panel
        settings.js
        i18n.js
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
