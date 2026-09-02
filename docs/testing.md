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

**E2E** — Playwright, five flows, no more:

1. App loads and an image appears
2. Space advances to a different artwork
3. `I` opens the metadata overlay
4. Language switches to Polish and back
5. With AI disabled, the overlay shows museum data and no error

Playwright is slow and flaky in proportion to how much you ask of it. Everything not in that
list belongs in a unit or integration test.

## Failure paths

Each of these has a named test. They are the ones that matter, because they are what a user
running the app for eight hours will actually hit:

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
uv run pytest -m e2e              # Playwright, needs the server running
uv run pytest --cov=app           # coverage when you want a number
```

CI runs the default selection plus `ruff` and `mypy`. It never runs `live` or `e2e`.
