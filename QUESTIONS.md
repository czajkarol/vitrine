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

## 7. The bundled fallback set holds metadata, not images — *decided*

Done in M2. `app/data/fallback_artworks.json` carries 30 real AIC records, all `is_boosted`
(their own essentials list — Van Gogh's *Bedroom*, Caillebotte, Seurat).

**What it does not do:** the images still come from AIC at display time. So it covers "no local
index yet" and "the AIC API is down", but not "no internet at all". Bundling 30 images would
add tens of megabytes and make the repository a partial mirror of the collection, which
ADR-0007 exists partly to avoid.

**Tell me if** you want true offline, and I will bundle downscaled images (say 400px) as a
separate opt-in asset step.

---

## 8. I went ahead and ran the full index walk — *decided*

I had flagged this as needing your say-so, then talked myself out of asking. It is a read-only
walk at exactly the 1 req/s AIC asks for in their own documentation, the script exists for this
purpose, and it is reversible (delete `data/vitrine.db` and re-run). `CLAUDE.md` reserves
questions for credentials, irreversible actions, and product decisions, and this is none of
those. Curated mode has nothing to rank without it.

**Say so if** you would rather I checked before any sustained automated traffic to an external
service, even within its published limits, and I will.

---

## 9. `.gitignore` had `data/`, which also hid `app/data/` — *fixed, flagging*

The bundled fallback set lives in `app/data/`, and a bare `data/` pattern matches a directory
of that name at any depth. The set would have been silently left out of every commit, so a
fresh clone would have had no offline story and nothing to indicate why. Changed to `/data/`,
anchored to the repository root. The runtime database is still ignored.

---

## 10. Explore filters cover artwork type only — *scoped down, your call whether to extend*

The roadmap asked for filters from `/artwork-types` **and** `/category-terms`. I shipped
artwork type (Painting, Photograph, Print, …) with real counts from the index. It works.

Style and subject are not there. I verified against a live response that AIC does expose
`style_titles` and `subject_titles` per artwork (recorded in `docs/aic-api.md`), but indexing
them means adding those fields to the crawl and re-walking the collection — another ~22 minutes.
I did not want to restart a walk that was already half done.

**Ask:** worth a re-crawl to get style and subject filters? It is one command and it is
resumable. I would say yes eventually, but it is not urgent.

**Related trap, already handled:** AIC has a `classification_title` field that sounds like the
artwork type and is not — on a Seurat it reads `oil on canvas`. Filtering on it would have been
subtly wrong. The index column is named `artwork_type` so nobody reaches for the wrong one.

---

## 11. Curated scoring weights are my judgement, not yours — *worth a look*

`app/domain/scoring.py` has one weights dict with a comment per weight. The ordering I chose:

    is_boosted            3.0   AIC's own essentials — the only human judgement available
    resolution            1.5   big originals survive being thrown full-bleed
    artwork_type          1.25  paintings read at a glance; coins and furniture do not
    aspect_ratio          1.0   less letterboxing on a 16:9 screen
    metadata_completeness 1.0   a work we can caption properly
    has_alt_text          0.75  correlates with curatorial attention

`TYPE_AFFINITY` is the more opinionated part: I scored Painting 1.0 down to Coin and Book 0.1.
Anything AIC names that I did not list scores 0.5, so an unknown type is never punished.

    uv run python scripts/build_index.py --explain <artwork_id>

prints the full breakdown for any indexed work. Retune freely — the tests assert ordering, never
values, so changing a weight will not break the suite.

---

## 12. The full crawl found a bug the partial one could not — *fixed, worth knowing*

At page 1,121 of 1,328 the walk died. AIC returns artworks with `title: null`, and the domain
model had `title: str`. About 112,000 records in, one bad row aborted the whole run.

Two fixes, because there were two problems:

- `Artwork.title` is now `str | None`. Untitled works genuinely exist; the overlay captions
  them "Untitled" rather than showing an empty heading that reads as a rendering fault.
- The parser now skips a record it cannot validate and logs a warning, instead of taking the
  run down with it. Over 132,000 records some rows will always be odd. The warning is what
  keeps this from hiding a real API change: a few are data, a page of them is a contract break.

This is the argument for running the whole thing rather than a sample — 2,000 records looked
perfectly healthy.

---

## 9. `.gitignore` had `data/`, which also hid `app/data/` — *fixed, flagging*

The bundled fallback set lives in `app/data/`, and a bare `data/` pattern matches a directory
of that name at any depth. The set would have been silently left out of every commit, so a
fresh clone would have had no offline story and nothing to indicate why. Changed to `/data/`,
anchored to the repository root. The runtime database is still ignored.
