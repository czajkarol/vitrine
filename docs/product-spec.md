# Product specification

Vitrine is closer to a screensaver than to a web app. One artwork, dark background, no chrome
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
5. On `decode()` rejection or image 404: log it, drop that artwork from the rotation, advance
   to the next candidate. Never show a broken image.

Using `decode()` rather than the `load` event is what makes the fade flicker-free — the browser
has finished decoding to a paintable bitmap before you touch opacity.

CSS transitions only. No `requestAnimationFrame` loops. Nothing should be animating at rest —
this app is idle 99% of the time and the GPU should know it.

### Colour

Tint the page background with the artwork's dominant colour, heavily desaturated and darkened,
and transition it alongside the crossfade. It makes the letterboxing feel intentional rather
than empty. Source the colour from the API `color` field if it exists, otherwise from `lqip`.
See `docs/aic-api.md` on which of those is confirmed.

---

## Rotation

- Intervals: 1, 5, 15, 30 minutes. Default 5.
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
1 2 3 4    set interval to 1 / 5 / 15 / 30 minutes
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

The user picks filters and gets random artworks matching them. Build filter options from
`/artwork-types` and `/category-terms` at index build time, not from a hardcoded list — a
hardcoded list will drift from what the API actually supports and produce empty result sets.

Only expose a filter if the local index has enough artworks behind it to sustain rotation.
A filter that yields four artworks is worse than no filter. Show the count.

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

API keys entered here are write-only in the UI — once saved, show `sk-…abcd`, never the value.

---

## Internationalisation

English default, Polish selectable. Every user-visible string comes from a translation resource
keyed by ID — including error messages, which are the strings most often left hardcoded.

Language selection drives the AI interpretation language too, and is part of the cache key.

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
