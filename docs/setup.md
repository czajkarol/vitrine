# Setup

From nothing to a picture on screen. Every step here was run on a fresh `git clone` on
2026-09-04; where the output is worth recognising, it is quoted.

The README's quick start is the three-line version. This is the one that says what each
step buys you and what to do when it does not work.

---

## 1. Prerequisites

- **Python 3.12 or newer.** `pyproject.toml` requires it and the code uses 3.12 syntax.
- **[uv](https://docs.astral.sh/uv/)**, which is what the commands here assume. Everything
  works with plain `pip` too: `python -m venv .venv`, activate it, then
  `pip install -e ".[dev]"` in place of `uv sync --all-extras`, and drop the `uv run`
  prefix from every command below.
- **A browser.** The app is a page; there is no desktop shell.

Windows, macOS and Linux all work. This repository is developed on Windows, and
`.gitattributes` normalises line endings so that the checkout is not the thing that differs
— if you see a whole file show as modified immediately after cloning, that is what it is
for and something has gone around it.

## 2. Install

```bash
uv sync --all-extras
```

`--all-extras` is worth taking. Each one buys something specific:

| Extra | Buys |
|---|---|
| `dev` | `pytest`, `ruff`, `mypy`, `respx`. Needed to run the suite at all |
| `keyring` | Decides whether a pasted API key is stored by the OS or left in plain text — see [data.md](data.md#where-a-key-actually-ends-up). Nothing fails without it; the settings panel simply says so before you type |
| `e2e` | Playwright. It needs one more step of its own: `uv run playwright install chromium` downloads the browser, which `uv sync` does not |

## 3. Configure

```bash
cp .env.example .env
```

**`AIC_USER_AGENT` is the one line you must actually change.** AIC has no API key; instead
they ask that every request identify the application and carry a contact address they can
reach if your traffic causes them a problem. Set it to your own:

```
AIC_USER_AGENT="vitrine (you@example.com)"
```

Leave it at the default and the app starts anyway but logs a warning on every boot, because
a header AIC would consider unhelpful is worse than a loud one.

Everything else in `.env.example` has a working default. Note that comments there sit on
their own line rather than trailing a key — that is deliberate and load-bearing:
python-dotenv strips a trailing comment only when a value comes before it, so
`AI_PROVIDER=  # mock | anthropic` on an empty key reads the comment itself as the value.
If you add settings of your own, keep to the same shape.

You do not need an AI key. AI is off by default and the app is complete without it
([ai-system.md](ai-system.md)).

## 4. Get an index

The app works with no index — it asks AIC for each artwork, and falls back to a bundled set
of thirty when the API is unreachable. An index makes selection a local SQLite query in
about 19ms, and it is what Explore's filters and Curated's ranking are built on
([ADR-0003](adr/0003-local-artwork-index.md)). Three ways to get one:

**a. Fetch a published export — fastest, no AIC traffic.**

```bash
uv run python scripts/fetch_index.py --url https://.../vitrine-index.sqlite --sha256 <digest>
```

About a second to merge, once the ~58MB has downloaded. It writes only the corpus tables,
so on an install you already use, your preferences, favourites and API key survive. Details
and the refusal rules are in [data.md](data.md#fetching-one).

**b. A partial walk — a few minutes, enough to see the app properly.**

```bash
uv run python scripts/build_index.py --limit 5000
```

**c. The full walk — 1,328 requests, about 30 minutes.**

```bash
uv run python scripts/build_index.py
```

Resumable and idempotent; progress is recorded after every page, so a re-run picks up where
it stopped. **It needs the owner's approval before it starts.** Not because it breaks AIC's
rate limit — it stays well inside their 60/min at one request per second — but because the
standing rule is about volume and duration rather than permission: half an hour of
automated traffic to somebody else's service is asked about first (`CLAUDE.md`,
`QUESTIONS.md` #8).

## 5. Run it

```bash
uv run uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>, press `F` for fullscreen, and leave it.

## 6. Verify

```bash
curl http://127.0.0.1:8000/api/health
```
```json
{"status":"ok","ai":{"enabled":false,"provider":null,"model":null,"circuit_open":false}}
```

`"ai": {"enabled": false}` with no key configured is correct, not a failure — it is how the
app tells the frontend not to offer the feature at all.

```bash
curl http://127.0.0.1:8000/api/stats
```

`indexed_artworks` is the number that says step 4 worked. Zero means the app is serving
from AIC and the bundled set, which looks fine on screen and is not what you wanted.

Then open the browser and look at it. Press `S` and open the "Artwork type" group: the facets
should show real counts, and the line above them the same total as `indexed_artworks`. Press `?`
in the same panel for the keyboard map.

## 7. The test suite

```bash
uv run pytest                       # 587 tests, no network
uv run ruff check . && uv run ruff format --check . && uv run mypy app
```

```bash
uv run playwright install chromium  # once
uv run pytest -m e2e                # 9 flows; they start their own servers
```

`uv run pytest -m live` hits the real AIC API, and a real AI provider if one is keyed. It is
excluded from the default run and from CI, and is run by hand when a contract test starts
looking suspicious. See [testing.md](testing.md).

## Troubleshooting

**A blank screen after editing a JS file, and the console says a module "does not provide an
export named X" for an export that is plainly there.** Chrome caches ES modules hard, and
there is no build step and no cache-busting to defeat it ([ADR-0005](adr/0005-vanilla-frontend.md)).
Refetch the changed file with `fetch(url, { cache: 'reload' })` from the console, then
reload the page.

**`data/vitrine.db-wal` and `-shm` appeared.** Normal. The database runs in
write-ahead-logging mode so the indexing script can write while the display reads. They are
part of the database — see [data.md](data.md#what-is-in-it).

**"No usable keyring backend" in the log, or the settings panel warning that a key will be
stored in plain text.** A warning, not a failure. The app falls back to storing the key in
SQLite and says so before you type anything. An installed `keyring` package with no working
backend counts as no keyring: it raises only when used, so it is probed rather than trusted.

**The app starts but every artwork takes a moment and the metadata looks thin.** No index —
you are on the second tier, straight from AIC. Check `indexed_artworks` in `/api/stats`.

**Nothing at all appears, and the log shows AIC errors.** Third tier: the bundled set of
thirty artworks covers "the API is down". It is metadata only, so it does not cover "no
internet at all" — the images still come from AIC's servers.

**A 429 from the app itself.** Its own rate limiter, not AIC's
(`RATE_LIMIT_*` in `.env`). The display waits out `Retry-After` on its own; if you are
hitting it by hand while testing, raise `RATE_LIMIT_BURST` or set it to `0` to turn
limiting off.
