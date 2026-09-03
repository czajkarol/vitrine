# Product specification

vitrine is closer to a screensaver than to a web app. One artwork, dark background, no chrome
unless asked for. It is meant to run for hours on a second monitor and be glanced at.

If a feature would make it feel more like a dashboard, it does not belong.

---

## The display

- One artwork at a time, centred, aspect ratio preserved, `object-fit: contain`.
- Background is near-black, not pure black — pure black makes dark artworks lose their edges.
- Optimised for 16:9. Other ratios must not break, but do not get bespoke layouts.
- No visible controls at rest. Everything appears on interaction and fades out again.

### The transition pipeline

This is the single most visible piece of engineering in the app. Get it right.

1. Paint `thumbnail.lqip` (the base64 blur) into the incoming layer immediately.
2. Construct the IIIF URL at the width chosen for this screen.
3. `const img = new Image(); img.src = url; await img.decode();`
4. Only after `decode()` resolves, start the crossfade. Two stacked layers, opacity transition.
5. On `decode()` rejection or image 404: retry once through `GET /api/image/{image_id}?w=…`,
   the proxy fallback from ADR-0008. Remember the outcome for the session, so that once a direct
   load has failed every later artwork goes straight to the proxy.
6. If the retry also fails: log it, drop that artwork from the rotation, advance to the next
   candidate. Never show a broken image.

Using `decode()` rather than the `load` event is what makes the fade flicker-free — the browser
has finished decoding to a paintable bitmap before you touch opacity.

**But `decode()` alone is not enough, and neither is `requestAnimationFrame`.** Both were
measured failing in Chrome on a *hidden* tab, which an ambient display is for much of its life:

- `img.decode()` never settles while the tab is hidden. It does not resolve and it does not
  reject; it simply stays pending. The `load` event on the same image fires normally.
- `requestAnimationFrame` callbacks do not run at all while the tab is hidden.

So the rule is: `decode()` decides while the tab is visible, which is the only time a flicker
could be seen; while it is hidden, a completed `load` is accepted instead. And never make an
element's visibility depend on an rAF callback — a class that gets added in rAF is a class that
never gets added, and the artwork stays at opacity 0 until something else forces a repaint.

Every image load also needs a deadline. Cloudflare does not reliably *reject* a blocked hotlink;
sometimes the request simply never answers. Without a timeout the rotation stalls on "Loading…"
forever, which the error-state rules below rule out.

CSS transitions only. No `requestAnimationFrame` loops. Nothing should be animating at rest —
this app is idle 99% of the time and the GPU should know it.

### Colour

Tint the page background with the artwork's dominant colour, heavily desaturated and darkened,
and transition it alongside the crossfade. It makes the letterboxing feel intentional rather
than empty. Source it from the API `color` field, which is confirmed present and carries HSL
plus a population count (`docs/aic-api.md`). It is `null` on works without an image, so keep the
`lqip` derivation as the fallback for that case only.

---

## Rotation

- Intervals: 30 seconds, 1, 5, 15, 30 minutes. Default 5 minutes.
- The interval is stored and passed around in **seconds**, because the shortest rung is not a
  whole number of minutes. `interval_seconds` on the preferences API, `INTERVAL_SECONDS` in
  `rotation.js`, one list in each.
- The *next* artwork is chosen and its image preloaded well before the current interval expires.
- Manual advance resets the timer.
- Never reload the page. Swap artwork state only.
- The timer must survive tab backgrounding sensibly. Browsers throttle timers in hidden tabs;
  on `visibilitychange` back to visible, check elapsed wall-clock time and catch up rather than
  trusting the interval fired on schedule.

---

## Keyboard

```
Space      next artwork
F          toggle fullscreen
I          toggle metadata overlay
1 2 3 4 5  set interval to 30 sec / 1 / 5 / 15 / 30 min
S          settings
Esc        close settings if open, else close overlay if open, else exit fullscreen
```

Esc priority is exactly that order — most transient thing first. Shortcuts are disabled while
focus is inside a text input.

---

## Metadata overlay

Appears on mouse movement and fades after a few seconds of stillness. `I` pins it open.

Shows: title, artist, date, medium, the AIC description when present, and credit to the
Art Institute of Chicago. When a description is shown, its CC BY attribution goes with it.

Museum facts and AI interpretation must be visually distinct — different container, a label,
not merely a smaller font. A user glancing at the screen must never mistake generated text
for a museum caption.

---

## Modes

### Explore

The user picks filters and gets random artworks matching them. Build filter options from what
the index actually contains, not from a hardcoded list — a hardcoded list will drift from what
the API supports and produce empty result sets.

Only expose a filter if the local index has enough artworks behind it to sustain rotation.
A filter that yields four artworks is worse than no filter. Show the count.

Filter on `artwork_type_title`, the vocabulary behind `/artwork-types`. Do **not** filter on
AIC's `classification_title`, which sounds like the same thing and is not — it is closer to a
medium (`oil on canvas`). See the table in `docs/aic-api.md`.

Style and subject filters (`style_titles`, `subject_titles`) are confirmed to exist but are not
indexed yet; adding them means extending the crawl's `fields=` and re-walking.

A filtered request is answerable only from the local index. AIC and the bundled set cannot
honour the filter, so a filter matching nothing returns nothing rather than quietly falling
through and showing a work the user filtered out.

### Curated

Transparent weighted scoring over the local index. No machine learning. Signals, all of which
come from real API data:

| Signal | Rationale |
|---|---|
| `is_boosted` | AIC's own essentials selection |
| Source resolution | `thumbnail.width/height`; bigger originals look better full-bleed |
| Aspect ratio | Closeness to the viewport ratio; less letterboxing |
| Metadata completeness | Artist, date, medium, description present |
| Has `alt_text` | Correlates with curatorial attention |
| Artwork type | Paintings and photographs display better than furniture or documents |
| Recency penalty | Seen in the last N artworks |

Weights live in one dict in one module, with a comment per weight. A `--explain` flag on the
index script should print the score breakdown for a given artwork. If you cannot explain in one
sentence why artwork A outranked artwork B, the scoring is too clever.

---

## History

Keep the last ~50 artwork IDs in SQLite. Use it to avoid near-term repeats, as a soft penalty
in scoring rather than a hard exclusion. An artwork seen two hours ago should be unlikely, not
impossible.

---

## Ambient mode

Keeps the screen awake while the app is displaying. Use the **Screen Wake Lock API**:
`navigator.wakeLock.request('screen')`. It requires a secure context, so localhost is fine.

Re-acquire the lock on `visibilitychange`, because browsers release it when the tab is hidden.
Handle the API being unavailable by hiding the toggle, not by erroring.

Do not write OS-level power management. Do not simulate input of any kind. This is a
display feature and the README describes it as one.

---

## Settings

A small panel, not a page. Interval, language, mode, filters, AI on/off, AI provider, metadata
visibility, ambient mode. Persisted locally. Opening settings pauses rotation; closing resumes.

Changing the interval while the panel is open must not restart the clock under it — set the new
interval, keep the clock held, and let closing the panel start it.

API keys entered here are write-only in the UI — once saved, show `sk-…abcd`, never the value.

---

## Internationalisation

English default, Polish selectable. Every user-visible string comes from a translation resource
keyed by ID — including error messages, which are the strings most often left hardcoded.

Language selection drives the AI interpretation language too, and is part of the cache key.

There is no plural machinery and there should not need to be. Polish inflects a counted noun
three ways — 1 dzieło, 2 dzieła, 5 dzieł — so a string whose grammar depends on a number cannot
be translated by substitution alone. Write the string so the number does not govern it:
`Dzieł w indeksie: {total}.` is right where `{total} dzieł` is right only sometimes.

---

## Error states

Every failure resolves to a calm on-screen state, never a stack trace and never a spinner that
spins forever:

- AIC unreachable → serve from the local index, show a small "offline" indicator
- Local index empty and AIC unreachable → show the bundled fallback set (see below)
- Image 404 → skip to next artwork, silently
- AI unavailable → overlay shows museum data only, with a quiet note
- AI budget exhausted → same, with a different note

Ship a bundled fallback set of ~30 artwork records in the repo so a fresh clone with no network
still displays something. It makes the first run work and it makes the offline story real.

---

## Accessibility

Keyboard reachable throughout. `alt` text from `thumbnail.alt_text`. Sufficient contrast on the
overlay. Honour `prefers-reduced-motion` by cutting instead of crossfading.
