# Open questions for Filip

Decisions I made on my own while you were away, and the few I would rather you settled.
Nothing here is blocking — the work is committed and the app runs. Overrule anything freely.

---

## 1. The overlay flashes on every artwork change  — *decided, please sanity-check*

`docs/product-spec.md` says the metadata overlay "appears on mouse movement and fades after a
few seconds of stillness", and that there should be "no visible controls at rest". Taken
literally, an untouched display never credits the Art Institute — and `CLAUDE.md` lists
"the UI must credit the Art Institute of Chicago" as a non-negotiable.

**What I did:** the overlay also reveals itself for ~3.5s whenever the artwork changes, then
fades on the usual idle timer. So every artwork is credited at least once while it is up, and
the screen is still bare at rest.

**Overrule it if** you would rather the display stayed completely blank until the mouse moves,
and we satisfy attribution some other way (a permanent hairline credit in a corner, say).

---

## 2. `S` for settings is not bound yet — *decided*

The spec lists `S` → settings, but the settings panel is M4. I left `S` unbound rather than
shipping a key that flashes "not available yet". The `Esc` priority chain (settings → overlay →
fullscreen) is already wired with a settings hook that currently reports "closed", so M4 only
has to fill it in.

---

## 3. Long AIC descriptions are clamped to 5 lines — *decided*

Some descriptions run several paragraphs and would cover the artwork they describe. The overlay
clamps to 5 lines with an ellipsis and caps the panel at 62 characters wide.

**Worth your opinion:** 5 lines is a guess. Options are a different clamp, a "more" affordance
(which starts to make it a dashboard), or scrolling (which I would avoid).

---

## 4. Rotation retries 20s after a failure, not a full interval — *decided*

When a fetch fails the app shows "The Art Institute is not responding. Retrying shortly." It
was then waiting the whole interval — up to 30 minutes — which made the message untrue. It now
retries after 20s. M2's local index will make this mostly moot.

---

## 5. Fullscreen is untested — *needs you, briefly*

`F` toggles fullscreen via the Fullscreen API. I could not verify it: `requestFullscreen()`
requires a real user gesture and synthetic key events do not qualify. Everything else in the
keyboard map is verified.

**Ask:** press `F` once and tell me if it misbehaves.

---

## 6. Image width is pinned to 1686 on this machine — *flagging, not asking*

`chooseWidth()` picks from AIC's cached ladder using viewport width x devicePixelRatio. On a
1920px viewport that lands on 1686, the largest rung, for every artwork. `docs/aic-api.md` says
843 is AIC's most-cached size and 1686 should be reserved for works that genuinely need it.

Since every image currently goes through our proxy anyway (Cloudflare blocks hotlinking,
ADR-0008), we are paying ~1MB per artwork through the backend where ~250KB would do.

**Options:** cap at 843 unless the display is genuinely high-DPI; or keep 1686 because an
ambient display on a big monitor is exactly the case where the larger file earns its keep.
I lean towards capping, but it is a visible-quality decision, so it is yours.

---

## 7. Fallback set / offline story is still M2

Nothing to decide, just so it is not a surprise: with no network there is currently no picture.
The bundled ~30-artwork fallback is an M2 item and I will do it there.
