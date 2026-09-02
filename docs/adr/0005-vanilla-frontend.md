# 0005. Vanilla frontend, no build step

Status: Accepted
Date: 2026-09-02

## Context

The frontend has one screen, roughly a dozen interactive elements, and no routing, no forms
beyond a settings panel, and no shared component surface. Its hardest problem is an image
transition pipeline, which is DOM and timing work rather than state management.

## Decision

Plain HTML, CSS, and ES modules served statically by FastAPI. No framework, no bundler, no
transpiler, no `node_modules`.

## Alternatives considered

**React.** Would add a build step, a dependency tree, and a hydration model to a page that
displays one image. Its strengths — component reuse, complex state — do not apply here.

**Web components.** More ceremony than a dozen elements justify.

## Consequences

No build step to break, nothing to keep patched, and the source in the browser is the source in
the repository. Debugging the transition pipeline means reading the code that runs.

The cost is manual DOM work and hand-rolled state. Kept in check by keeping state in one module
with explicit setters. If the UI ever grows a second screen with shared components, revisit.
