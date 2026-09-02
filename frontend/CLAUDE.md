# Frontend rules

Loaded when working inside `frontend/`. Behaviour is specified in `docs/product-spec.md`.

- No framework, no bundler, no `node_modules`. ES modules loaded directly by the browser.
- Only `js/api.js` calls `fetch()`.
- State lives in one module as a plain object with explicit setters.
- Image swaps go through the pipeline in `docs/product-spec.md`: paint `lqip`, then
  `new Image()`, then `await img.decode()`, and only then crossfade. Never swap on the `load`
  event — it fires before the bitmap is paintable and the fade will flicker.
- CSS transitions only. No `requestAnimationFrame` loops. Nothing animates at rest.
- Remove event listeners and clear timers when a component tears down. This app runs for hours;
  a leaked listener per rotation is thousands by morning.
- Every user-visible string comes from `locales/`. That includes error messages.
- Build IIIF URLs only at the cached widths: 200, 400, 600, 843, 1686. Never an arbitrary width.
- Keyboard handlers are inert while focus is in a text input.
