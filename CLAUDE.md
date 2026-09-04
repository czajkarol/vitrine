# CLAUDE.md

vitrine — an ambient digital-art display. It shows one public-domain artwork at a time,
full-bleed on a warm dark ground, rotating on a timer. The Art Institute of Chicago is the
primary source and the only indexed one; the Cleveland Museum of Art is selectable and served
live (ADR-0013). Python/FastAPI backend, vanilla-JS frontend, SQLite. Runs locally on the
developer's machine.

The project name is provisional. If it is going to change, change it in M0 before any other work.

**The name is written `vitrine`, lower case, always.** Including at the start of a sentence, in
headings, in the browser tab title, and in prose. Not `Vitrine`. Sentence-casing autocorrects
itself back constantly, so if you find a capital V, fix it.

---

## Non-negotiables

- Never commit secrets. API keys live in `.env`, which is gitignored.
- Never send provider API keys to the frontend. All AI calls go through the backend.
- Only display artworks the source flags as freely reusable — `is_public_domain == true` at the
  Art Institute, `share_license_status == "CC0"` at Cleveland. A hard filter, not a preference,
  and checked on the way out as well as asked for in the query.
- The app must be fully usable with no AI provider configured. AI is an enhancement, never a dependency.
- **The repository is written in English.** Code, comments, docs, ADRs, commit messages,
  identifiers, test names, branch names — all of it, whatever language the conversation about
  the work happens in. The one exception is user-facing copy, which lives in
  `frontend/locales/` and is translated; Polish belongs there and nowhere else.
- No frontend framework. No React, Vue, Svelte, or build step. Plain HTML/CSS/JS modules.
- Do not invent AIC API fields. If a field is not confirmed in `docs/aic-api.md`, verify it against
  a live response before building on it, then record what you found.

---

## AIC API — constraints you cannot derive from the code

These are the pitfalls that will silently break things. Full detail in `docs/aic-api.md`.

- **60 requests/minute per IP, anonymous.** The client needs its own throttle. There is no API key.
- **`/artworks/search` caps at 1,000 records** (`page × limit ≤ 1000`), not 10,000 — measured,
  not read off the docs. You cannot paginate the collection through search. This is why the
  corpus is indexed locally — see ADR-0003.
- **`/artworks` (the plain listing endpoint) is not capped.** It walks all 132,740 records at
  `limit=100`. That, not the nightly data dump, is how `scripts/build_index.py` gets its corpus.
- **`limit` cannot exceed 100.** Default is 12.
- **Send an `AIC-User-Agent` header** with the project name and a contact email on every request.
- **Never hardcode the IIIF base URL.** It is in `config.iiif_url` on every API response.
- **Request image width `843`.** It is AIC's most-cached size. `1686` only for public-domain works
  that genuinely need it.
- **Hotlinking is blocked by Cloudflare; try direct, then fall back to the proxy.** Getting a
  `200` from the IIIF service needs an `AIC-User-Agent` header, and an `<img>` tag cannot send
  one. The frontend attempts the direct URL and retries once via `GET /api/image/{image_id}`.
  Do not proxy unconditionally, and do not scrape. See ADR-0008.
- **Any image can be unpublished or replaced at any time.** Handle 404s on images at display time,
  and treat the local index as a cache that goes stale, not as truth.
- **Licensing:** the `description` field is CC BY 4.0 and requires attribution. Everything else is
  CC0. The UI must credit the Art Institute of Chicago.

Fields worth building on, confirmed present in search responses:
`thumbnail.lqip` (base64 blur placeholder — use it for transitions), `thumbnail.alt_text`
(human-written visual description — use it for accessibility *and* to ground AI prompts),
`thumbnail.width` / `height`, `is_boosted` (AIC's own curatorial signal — feed it into Curated scoring).

---

## Architecture boundaries

Dependency direction, strictly one-way:

```
frontend  →  api  →  services  →  domain  →  providers / repositories  →  outside world
```

- `domain/` imports nothing from `providers/`, `repositories/`, `api/`, or `httpx`.
- Each museum's client is the only module that knows that museum's response shape. Both return
  domain models.
- AI providers sit behind one interface. Nothing outside `providers/ai/` names a vendor — a
  vendor-specific *capability* is a second Protocol, not a name compared somewhere else.
- **The AI features are grounded in AIC's `thumbnail.alt_text`, so they are offered on AIC
  artworks only.** A source without it needs a different prompt or no AI, and that is a decision
  to take out loud rather than arrive at (ADR-0013, ADR-0015).
- Config is injected, never read from the environment deep inside a call stack.

Read `docs/architecture.md` before adding a module or moving one between layers.

---

## Where to read what

Do not read these upfront. Read the one that matches the task, when the task comes up.

| Working on | Read first |
|---|---|
| Anything touching AIC requests or fields | `docs/aic-api.md` |
| A second museum, or the `ArtworkSource` seam | `docs/adr/0013-cleveland-as-a-live-source.md` |
| Features, modes, UI behaviour, shortcuts | `docs/product-spec.md` |
| Layers, module placement, interfaces | `docs/architecture.md` |
| AI providers, caching, prompts, budgets | `docs/ai-system.md` |
| Setting the project up, or a step that will not work | `docs/setup.md` |
| Publishing or fetching an index, or what is stored where | `docs/data.md` |
| What to build next | `docs/roadmap.md` |
| Why something is the way it is | `docs/adr/` |

`app/`, `frontend/`, and `tests/` each have their own CLAUDE.md with rules scoped to that subtree.

---

## Working agreement

Work autonomously through `docs/roadmap.md`. Pick the next unchecked item, build it, tick it off.

Ask only for: credentials or external accounts, an irreversible action, a product decision that
genuinely changes what the app *is*, or **sustained automated traffic to an external service**.
Anything else, decide and note the decision in the commit message. If a decision is architectural
and would be expensive to reverse, write an ADR.

On that last one, the owner's rule, and the threshold is volume and duration rather than
permission:

> For sustained automated traffic to an external service, ask first if the operation is expected
> to run for several minutes or generate a substantial number of requests, even when it stays
> within the documented API limits. Short, low-volume requests within documented limits can be
> performed autonomously.

So a handful of calls to check a field is yours to make. A full `scripts/build_index.py` walk —
1,328 requests over 22 minutes — is not, even though it sits inside AIC's own 1 req/s etiquette.

Build vertically. A working thin path through every layer beats a complete layer with nothing on
top of it. If there is no picture on screen yet, the next task is the one that puts a picture on
screen.

When something in these docs turns out to be wrong or unworkable, fix the doc in the same commit
as the code. Stale specs are worse than no specs.

---

## Definition of done

A change is done when tests covering its logic pass, `ruff` and `mypy` are clean, the failure
path is handled, and it is committed with a message that says why. For anything that renders,
that also means you opened it in a browser and looked at it.

Do not add "verify your work" ceremony beyond this. Run the checks once, read the result, move on.

---

## Commands

```bash
uv sync --all-extras          # or: pip install -e ".[dev]"
uv run python scripts/run.py  # serve, then open a browser once it answers
uv run uvicorn app.main:app --reload          # the same, without the browser
uv run pytest                 # excludes live/e2e by default
uv run pytest -m live         # hits the real AIC API, run manually
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run python scripts/build_index.py --limit 5000
uv run python scripts/export_index.py         # publishable corpus → dist/, no network
uv run python scripts/fetch_index.py --file dist/vitrine-index.sqlite
```
