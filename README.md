# Vitrine

An ambient digital-art display. One public-domain artwork from the Art Institute of Chicago at
a time, full-bleed on a dark background, rotating on a timer. Built for a second monitor.

> This README is a stub. It gets written properly in M6 — see `docs/roadmap.md`. It should end
> up covering architecture, setup, the AI system, caching, testing, performance, security,
> limitations, and how the project was built.

## Status

Early. See `docs/roadmap.md` for what is done and what is next.

## Quick start

```bash
uv sync --all-extras
cp .env.example .env          # set AIC_USER_AGENT to your project name and email
uv run python scripts/build_index.py --limit 5000
uv run uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>.

AI interpretation is optional and off by default. Everything else works without it.

## Documentation

| | |
|---|---|
| `docs/product-spec.md` | What the app does and how it behaves |
| `docs/architecture.md` | Layers, boundaries, data flow |
| `docs/aic-api.md` | AIC API constraints, fields, licensing |
| `docs/ai-system.md` | Providers, caching, prompts, cost control |
| `docs/testing.md` | Test strategy |
| `docs/adr/` | Why things are the way they are |

## Attribution

Artwork data and images come from the Art Institute of Chicago's public API. Collection data is
CC0; the `description` field is CC BY 4.0. See <https://www.artic.edu/terms>.

## How this was built

Implementation was done by Claude Code working autonomously against the specification in
`CLAUDE.md` and `docs/`, with me as reviewer and product owner. The architectural decisions,
and the reasoning behind them, are recorded in `docs/adr/`.
