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
2. Construct the IIIF URL at the width chosen for this screen **and clamped to the artwork's
   own `thumbnail.width`**. AIC's IIIF service answers `403` for a width larger than the source
   and will not upscale, so asking for one is not merely wasteful, it is a skipped artwork. On a
   monitor wide enough to want 1686, that silently dropped 8,993 of the 57,607 indexed works —
   one in six — at any size at all. Found in a browser on a print that is 1602px wide.
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

The same field's `l` also picks the overlay scrim: above 60, the artwork gets a stronger and
taller gradient. **It is a hint, not a measurement, and the design must not depend on it.** AIC
reports the dominant colour of the whole image, and a Winslow Homer watercolour drawn in
graphite on tan paper comes back at `l = 6` — as dark as anything in the collection — while
reading as a bright cream ground under the caption. So the default scrim is strong enough on its
own and the light variant only adds to it. Measured on that Homer, in a browser.

### Typography

Two voices. The museum's words — title, artist, date, medium, description, credit — are set in
**EB Garamond**; the interface, the settings panel, the status pill and the AI section stay in
the system sans. An interface should look like one.

The font is self-hosted in `frontend/fonts/`, not pulled from a CDN: the app has to work with no
network, and ADR-0005's "the source in the browser is the source in the repository" is as true
of a font as of a script. Copyright 2017 The EB Garamond Project Authors, **SIL Open Font
License 1.1**, whose text ships beside the files in `frontend/fonts/OFL.txt` as the licence
requires. Two files — one variable `woff2` per Unicode subset, `latin` and `latin-ext`, covering
weights 400–600 between them. `latin-ext` is not optional: the Polish locale puts diacritics
into the serif on every artwork through the attribution line.

Garamond designs have a small x-height and run light on screen, so the type scale is part of the
choice rather than a polish pass — the description sits at 1.0625rem with `line-height: 1.6`,
and the measure widens to 68ch to match. `font-display: swap`, with Georgia at the head of the
fallback stack: a readable caption in Georgia beats an invisible one in Garamond.

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
L          add to favourites, or remove
X          hide this artwork — never show it again, in any mode
1 2 3 4 5  set interval to 30 sec / 1 / 5 / 15 / 30 min
S          toggle settings
Esc        close settings if open, else close overlay if open, else exit fullscreen
```

Esc priority is exactly that order — most transient thing first. Shortcuts are disabled while
focus is inside a text input — except Esc itself, which always closes. The panel holds one text
field, the API key, and a field you cannot escape from is a panel you cannot close.

`S` **toggles** rather than only opening. In fullscreen the browser takes `Esc` for itself and
uses it to leave fullscreen, so a key that opens the panel and cannot close it leaves no
keyboard way out of the panel that does not also drop out of the one state this app is meant to
sit in. `QUESTIONS.md` #2, amended.

`Space` and the overlay's advance button share one 1500ms cooldown. A press inside the window is
ignored rather than queued — a queued advance arrives after the user has stopped asking for
one — and the button is visibly disabled for the duration rather than silently inert.

---

## Metadata overlay

Appears on mouse movement and fades after a few seconds of stillness. `I` pins it open.

Shows: title, artist, date, medium, the AIC description when present, and credit to the
Art Institute of Chicago. When a description is shown, its CC BY attribution goes with it.

Museum facts and AI interpretation must be visually distinct — different container, a label,
not merely a smaller font. A user glancing at the screen must never mistake generated text
for a museum caption. They are also set in different faces: the museum speaks in the serif, the
machine in the interface sans.

### The description, and expanding it

The description clamps to five lines. That is the resting state and does not change.

A small `i` button beside it expands it in place, bounded to 45vh and scrollable past that. It
appears only when the clamp is actually hiding something — measured from `scrollHeight`, not
guessed from how many characters the text has, because five *lines* depends on the viewport and
on which font won the `font-display: swap` race.

Expansion is per artwork and temporary. It collapses when the artwork rotates, on `Esc`, and
when the overlay fades. While it is open the idle fade stretches from 3.5s to 20s, because
reading is not moving the mouse and 3.5s takes the text away mid-paragraph; scrolling the
description counts as activity for the same reason. An unattended display still returns to the
artwork on its own, which is what the original ruling protects. `QUESTIONS.md` #3, amended.

`I` keeps its own meaning — pin or unpin the whole overlay. Two affordances, two meanings.

### Controls on the display

The two buttons above are the only clickable controls outside the settings panel, and they live
inside the overlay, which is hidden at rest. "No visible controls at rest" is unaffected.

The overlay itself keeps `pointer-events: none` so it cannot swallow the movement that reveals
it; the buttons and the expanded description take the pointer back one element at a time.

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

Style and subject (`style_titles`, `subject_titles`) are filters too, added in M3.5. They differ
from artwork type in one way that shows in the UI: type is a closed vocabulary and all of it can
be offered, while style and subject run to hundreds of facets, so only the most populous sixty
are — on top of the same "enough behind it" rule. A group with nothing to offer is hidden rather
than shown empty.

The three combine with AND, and each takes one value rather than several. "Landscape **and**
portraits" narrows to almost nothing and reads as a bug rather than as a filter, so the panel
offers radio buttons and not checkboxes.

A filtered request is answerable only from the local index. AIC and the bundled set cannot
honour the filter, so a filter matching nothing returns nothing rather than quietly falling
through and showing a work the user filtered out.

#### The vocabulary is ours, not the museum's

Since M10 the options are **canonical facets**, not AIC's raw cataloguing — see ADR-0009 and
`app/domain/vocabulary.py`. AIC's own vocabulary is correct as cataloguing and unusable as a
menu: `portrait` and `portraits` were two options, the panel implied 3,169 portrait artworks
where there are 2,126, and the third most common "subject" in the collection is
`Collected by Hugh Edwards`, which is provenance.

A facet key (`style.japanese`) is the API value, the saved preference and the i18n key, and is
permanent once shipped. Labels come from `locales/` like every other string, falling back to the
English the server sends — so an untranslated facet reads as a word, never as a slug.
`locales/en.json` deliberately carries no facet keys at all: the server's label *is* the English
label, and a second copy would only be somewhere for it to drift.

#### Exclusion

Each group also offers a collapsed **Exclude** sub-list, and it is checkboxes where inclusion is
radios. That is not an inconsistency: the reasoning above applies to inclusion and simply is not
true of exclusion. Ruling several things out at once is ordinary and leaves plenty behind.

Including and excluding the same facet is contradictory rather than empty, and returns the usual
"nothing matches those filters" — never a silently dropped exclusion.

#### Counts follow the selection

The number beside an option is what choosing it would actually yield **under the rest of the
current selection**, computed leave-one-out: each group is counted under the other groups'
choices but not its own. So choosing a style updates the subject and type counts, and the style
list the user is standing in does not collapse around their own choice.

What is *offered at all* is decided separately and unconstrained, against the same "enough behind
it" rule — a filter the index cannot sustain is not a filter whatever else is selected, and
re-deciding it under the selection would make options appear and vanish as the user clicks. An
option whose constrained count is zero stays, at zero, shown disabled. A list that reshuffles
under the cursor is worse than a greyed row.

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

### For you

A third mode, and deliberately not a change to Curated — see ADR-0010.

`L` and `X` are the entire input. No dwell time, no skips, no inference from silence: an
ambient display is left running in an empty room, and "watched for nine minutes" usually means
nobody was there.

Ranking is `curated × (1 + α · affinity)`, so curated quality still bounds it: a blurry
favourite subject does not beat a well-photographed one. The affinity is frequency over the
canonical facets of what you have liked, weighted by group — subject says more about a person
than artwork type does, because half the collection is prints and liking prints is close to
saying nothing.

**Below five likes it says so.** The mode falls back to curated ranking, the response carries
`personalised: false`, and the display shows one line explaining that it is showing Curated
picks for now. A recommendation that is not one is worse than no recommendation.

Hidden artworks are excluded in **every** mode, including plain Random. `X` means never again,
and switching modes is not a change of mind about it.

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

API keys entered here are write-only in the UI — once saved, show `…abcd`, never the value.
The panel also says where the key is kept: the OS keyring, or unencrypted in the app's own
database when there is no keyring to use. That line is shown before anything is typed, not
after, because it is what someone needs in order to decide whether to type at all.

A key configured in `.env` is shown as such and cannot be removed from here — it is a file the
user edits themselves. A key saved here overrides one in `.env`, and takes effect without a
restart.

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
- Rate limited (429) → one calm line, and **wait out `Retry-After` exactly**

---

## Rate limiting

`/api/artwork/random` and `/api/image/{image_id}` are limited. They are the two routes whose
cost leaves the machine: with an index present, serving an artwork makes no AIC call at all, so
the outbound cost of an advance is one IIIF image fetch. Nothing else is limited — bounding
`/api/preferences` would bound nothing and would make the settings panel feel broken.

Burst 10, one token back every 3s (20 a minute sustained), and a rolling ceiling of 400 an hour.
All three are `RATE_LIMIT_*` in `.env`; `RATE_LIMIT_BURST=0` turns it off. This is not about
AIC's documented 60 requests/minute, which the index keeps us far below. It is about not leaning
on someone else's CDN and about bounding a tab that got stuck overnight.

**The unit is an advance, not a request.** Showing one artwork is two requests — the artwork,
then its image through the proxy when the direct load was blocked — so an allowed artwork
request grants a credit that its image spends. Without that the limiter caused the storm it
exists to prevent: an `<img>` cannot see a `429`, so the display read a refused image as a dead
one, dropped the artwork and asked for another immediately. Measured in a browser; it did not
recover on its own. A proxy call with no advance behind it still pays full price.

On the display side, a `429` is the one failure the user can make worse, so it is the one that
locks the controls: the manual advance is held for exactly `Retry-After`, and the rotation
clock backs off by the same amount instead of its usual 20 seconds. Never a retry sooner than
the server asked for.

Ship a bundled fallback set of ~30 artwork records in the repo so a fresh clone with no network
still displays something. It makes the first run work and it makes the offline story real.

---

## Accessibility

Keyboard reachable throughout — including the overlay's two buttons, which are real `<button>`
elements in the tab order, and which leave the tab order with the overlay when it fades.
`alt` text from `thumbnail.alt_text`. Sufficient contrast on the overlay. Honour `prefers-reduced-motion` by cutting instead of crossfading.
