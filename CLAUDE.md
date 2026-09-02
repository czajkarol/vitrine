# CLAUDE.md

Vitrine — an ambient digital-art display. It shows one public-domain artwork from the
Art Institute of Chicago at a time, full-bleed on a dark background, rotating on a timer.
Python/FastAPI backend, vanilla-JS frontend, SQLite. Runs locally on the developer's machine.

The project name is provisional. If it is going to change, change it in M0 before any other work.

---

## Non-negotiables

- Never `git push`, force-push, or rewrite history. Local commits only, unless told otherwise.
- Never commit secrets. API keys live in `.env`, which is gitignored.
- Never send provider API keys to the frontend. All AI calls go through the backend.
- Only display artworks where `is_public_domain == true`. This is a hard filter, not a preference.
- The app must be fully usable with no AI provider configured. AI is an enhancement, never a dependency.
- No frontend framework. No React, Vue, Svelte, or build step. Plain HTML/CSS/JS modules.
- Do not invent AIC API fields. If a field is not confirmed in `docs/aic-api.md`, verify it against
  a live response before building on it, then record what you found.

---

## AIC API — constraints you cannot derive from the code

These are the pitfalls that will silently break things. Full detail in `docs/aic-api.md`.

- **60 requests/minute per IP, anonymous.** The client needs its own throttle. There is no API key.
- **Search endpoints cap at 10,000 records** across any `limit`/`page` combination. You cannot
  paginate through the collection. This is why the artwork corpus is indexed locally — see ADR-0003.
- **`limit` cannot exceed 100.** Default is 12.
- **Send an `AIC-User-Agent` header** with the project name and a contact email on every request.
- **Never hardcode the IIIF base URL.** It is in `config.iiif_url` on every API response.
- **Request image width `843`.** It is AIC's most-cached size. `1686` only for public-domain works
  that genuinely need it.
- **Do not proxy or scrape images.** AIC serves them with `Access-Control-Allow-Origin: *` and
  explicitly permits hotlinking. A proxy adds a failure mode and bandwidth cost for nothing.
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
- The AIC client is the only module that knows AIC's response shape. It returns domain models.
- AI providers sit behind one interface. Nothing outside `providers/ai/` names a vendor.
- Config is injected, never read from the environment deep inside a call stack.

Read `docs/architecture.md` before adding a module or moving one between layers.

---

## Where to read what

Do not read these upfront. Read the one that matches the task, when the task comes up.

| Working on | Read first |
|---|---|
| Anything touching AIC requests or fields | `docs/aic-api.md` |
| Features, modes, UI behaviour, shortcuts | `docs/product-spec.md` |
| Layers, module placement, interfaces | `docs/architecture.md` |
| AI providers, caching, prompts, budgets | `docs/ai-system.md` |
| What to build next | `docs/roadmap.md` |
| Why something is the way it is | `docs/adr/` |

`app/`, `frontend/`, and `tests/` each have their own CLAUDE.md with rules scoped to that subtree.

---

## Working agreement

Work autonomously through `docs/roadmap.md`. Pick the next unchecked item, build it, tick it off.

Ask only for: credentials or external accounts, an irreversible action, or a product decision that
genuinely changes what the app *is*. Anything else, decide and note the decision in the commit
message. If a decision is architectural and would be expensive to reverse, write an ADR.

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
uv run uvicorn app.main:app --reload
uv run pytest                 # excludes live/e2e by default
uv run pytest -m live         # hits the real AIC API, run manually
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run python scripts/build_index.py --limit 5000
```
