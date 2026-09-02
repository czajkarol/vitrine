# Backend rules

Loaded when working inside `app/`. Layer boundaries are in `docs/architecture.md`.

- `domain/` imports nothing from `providers/`, `repositories/`, `api/`, `httpx`, or `sqlite3`.
  If you reach for one of those here, the logic belongs in a different layer.
- Only `providers/aic/` knows AIC's JSON shape. It returns domain models, never raw dicts.
- Only `providers/ai/` names an AI vendor. No vendor branching anywhere else.
- Every outbound response is parsed through a Pydantic model. AIC returns `null` rather than
  empty strings, and `[]` rather than `null` for list fields — model accordingly.
- Config is injected. No `os.environ` reads below `core/config.py`.
- No raw SQL outside `repositories/`.
- Async all the way down for I/O. Do not mix a sync SQLite call into an async request path
  without moving it to a thread.
- Catch specific exceptions. A bare `except Exception` that swallows and continues is a bug
  unless it is the top-level handler and it logs.
- API keys are redacted to the last four characters in every log line, error, and response.
