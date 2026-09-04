# Decisions

The owner ruled on all twelve open questions on 2026-09-03. They are settled; this is the record
of what was decided and why, so nobody relitigates them.

All twelve are now closed: **#5** was confirmed by hand on 2026-09-03.

Two entries have since been reopened deliberately and amended in place, with the date and the
reason — **#2** and **#3**, both on 2026-09-03 as part of M7. **#3 carries a second amendment
from 2026-09-04 (M13)**, where the `i` control became a details toggle shown on every artwork.
An amendment is how a ruling changes here. Contradicting one in the code while leaving this file
saying the opposite is not.

---

## 1. The overlay flashes on every artwork change — **keep**

The overlay reveals itself for ~3.5s whenever the artwork changes, then fades on the usual idle
timer. `docs/product-spec.md` asks for "no visible controls at rest", but read literally that
means an untouched display never credits the Art Institute, which `CLAUDE.md` makes
non-negotiable.

> Showing the attribution for ~3.5s when the artwork changes is a good compromise. I do not want
> a permanent credit in the corner.

A permanent hairline credit was the alternative and is explicitly rejected.

---

## 2. `S` for settings — **bound, and from M8 it toggles**

The original ruling:

> Leave it unbound until M4. There is no point pretending the settings panel exists before it
> does.

**This was answered against a stale question.** The entry was written during M1, when the panel
did not exist. M3 then built a real settings panel to hold the Explore filters, and `S` opens it.

So `S` is not pretending — and unbinding it now would leave **no way to reach Explore filters or
the mode switch at all**, since the panel has no other entry point. Left bound for that reason.

**Amended 2026-09-03 (M7).** Closed. `S` stays bound, and M8 makes it *toggle* rather than only
open. The reason is not preference: in fullscreen the browser owns `Esc` and uses it to leave
fullscreen, so with the panel open there was no keyboard way to close the panel without also
dropping out of fullscreen — which is the one state this app is meant to sit in. A key that
opens but cannot close is a dead end wherever `Esc` is spoken for.

---

## 3. Five-line description clamp — **kept as the resting state; expansion added in M8**

Descriptions clamp to 5 lines with an ellipsis, panel capped at 62 characters wide.

> Keep 5 lines + ellipsis. Do not add scrolling or a "more" affordance. This is an ambient
> display, not a dashboard. We can revisit it later if real usage shows a problem.

**Amended 2026-09-03 (M7).** The owner has asked for the expand affordance, taking up the
"revisit it later" the original ruling left open. This is a reversal of the second sentence
only, and the reasoning behind the first survives it intact:

- The five-line clamp **stays as the resting state**. Nothing changes about what an untouched
  display shows.
- Expansion is opt-in per artwork, behind a small `i` button that appears only when the text is
  actually clamped, and it collapses on rotation, on `Esc`, and when the overlay fades. An
  expanded essay is never what an unattended display settles on, which is what "not a dashboard"
  was protecting.

Design in `docs/plan-improvements.md` Phase 1.3; built in M8.

**Amended again 2026-09-04 (M13).** The owner asked for the `i` control to be shown consistently,
"including artworks without descriptions". That reverses the "appears only when the text is
actually clamped" clause above, and the reason is worth keeping: measuring `scrollHeight` was the
right way to decide whether the *clamp* was hiding anything and the wrong way to decide whether
the *control* should exist. Roughly seven artworks in eight have no description at all, and on
those the button vanished — which reads as a rendering fault rather than as an absence, and left
no way to discover from the screen that the affordance was there.

So `i` is a **details** toggle rather than an expand button. It opens the description where there
is one, and either way it opens four catalogue facts the overlay has no room for at rest, all of
which were already on the response and on screen nowhere.

Two clauses of the original ruling survive and are strengthened rather than weakened:

- The resting state is still the five-line clamp, and still what an untouched display shows.
- An expanded panel is still never where an unattended display settles: it collapses on rotation,
  on `Esc` and when the overlay fades, exactly as before. M13 also **holds the rotation** while it
  is open, which is the other half of the problem the stretched idle fade only half solved — text
  staying put while the picture underneath it changes is no better than the text going away.

---

## 4. Twenty-second retry after a failure — **keep**

A failed fetch retries in 20s rather than waiting out the whole rotation interval, which on the
30-minute setting made "Retrying shortly" untrue.

> This is better UX than waiting for the full rotation interval.

---

## 5. Fullscreen — **verified by hand; works**

`F` toggles fullscreen via the Fullscreen API. It could not be verified from automation:
`requestFullscreen()` requires a real user gesture and synthetic key events do not qualify.
Everything else in the keyboard map was verified in a browser.

> I will test `F` manually and let you know if anything behaves incorrectly.

Tested on 2026-09-03:

> fullscreen by F works fine

Closed. Worth remembering the shape of it rather than the answer: a real user gesture is the
one thing browser automation cannot fake, so anything gated on one needs a human keypress and
should be handed over deliberately rather than left to look untested.

---

## 6. Image width — **keep 1686; the selection logic was checked and is correct**

> Keep 1686 as the default for my use case. This is an art display running on a large monitor,
> so image quality matters more than aggressively minimizing bandwidth. However, `chooseWidth()`
> should still select the size based on the actual viewport/render size/DPR.

Checked, and it does. `chooseWidth()` takes viewport width x devicePixelRatio and picks the
smallest cached rung that covers it:

    viewport  600 @ 1.0  ->  600
    viewport  800 @ 1.0  ->  843
    viewport 1280 @ 1.0  -> 1686
    viewport 1920 @ 1.0  -> 1686

1686 is not hardcoded; it is simply the top rung, and any viewport needing more than 843
effective pixels lands there. On a large monitor that is the right answer. No change made.

One nuance, recorded and deliberately not acted on: for a **portrait** artwork the rendered
width is far narrower than the viewport, because `object-fit: contain` fits to height. Width
selection therefore overestimates for tall works. Fixing it means deriving render width from the
source aspect ratio. Worth doing only if bandwidth becomes a real complaint.

---

## 7. Bundled fallback images — **do not bundle**

`app/data/fallback_artworks.json` carries metadata for 30 real AIC records; the images still
come from AIC at display time. So it covers "no local index" and "the AIC API is down", not
"no internet at all".

> Do not bundle the images. The metadata-only fallback is sufficient. I do not need true offline
> mode or a separate asset pack right now.

---

## 8. Sustained external traffic — **new standing rule, now in `CLAUDE.md`**

I ran a 22-minute, 1,328-request crawl after saying I would ask first. The owner's rule:

> For sustained automated traffic to an external service, ask me first if the operation is
> expected to run for several minutes or generate a substantial number of requests, even when it
> stays within the documented API limits. Short, low-volume requests within documented limits can
> be performed autonomously.

Written into the Working agreement section of `CLAUDE.md`. The threshold is volume and duration,
not permission: a few calls to verify a field are fine; a full index walk needs approval first.

---

## 9. `.gitignore` `/data/` anchoring — **keep**

A bare `data/` matches a directory of that name at any depth and was silently excluding
`app/data/fallback_artworks.json`, the bundled offline set. Anchored to `/data/` so only the
runtime database at the repository root is ignored.

> Keep the `/data/` fix. That is the correct behavior.

---

## 10. Style and subject filters — **wanted, but not by re-crawling now**

Explore currently filters on artwork type only. `style_titles` and `subject_titles` are verified
to exist (`docs/aic-api.md`) but are not indexed.

> Yes, I want them eventually, since they were part of the roadmap and fit Explore well. However,
> do not run another 22-minute crawl just to add them immediately. Make the re-crawl a separate
> planned step when we work on the full indexing/filtering functionality.

Recorded as its own roadmap item so it is picked up deliberately, alongside whatever else needs a
walk, rather than triggering a crawl on its own.

Done, 2026-09-03, exactly that way: M3.5. The ruling is unchanged; this note is here only so the
first sentence above is not read as the current state. Style and subject are indexed and
filterable, and the walk that added them was approved first.

---

## 11. Curated scoring weights — **accepted as heuristics, not truths**

> Accept the current weights for now. I like that they are explicit, documented, and that
> `--explain` provides the breakdown. Treat the weights as transparent heuristics, not objective
> truths. In particular, comments such as "paintings read at a glance; coins and furniture do
> not" should be understood as our product heuristics, not facts. Keep the scoring easy to tune
> later.

The comments in `app/domain/scoring.py` were reworded to say so plainly, because the originals
read like statements of fact about art. Values unchanged; tests still assert ordering only, so
retuning a weight never breaks the suite.

---

## 12. Null titles and the resilient parser — **keep**

`Artwork.title` is `str | None`, the overlay captions untitled works "Untitled", and the parser
skips records it cannot validate with a warning rather than aborting the run.

> Definitely keep this. I also like the distinction between individual malformed records and a
> sudden large increase in validation failures — the latter should be treated as a potential API
> contract break.

That distinction is written into the docstring on `AicClient._parse_records`: a handful of skips
is data, a page of them is a contract break. If skip counts ever need to be acted on rather than
read, `/api/stats` in M6 is where the counter belongs.
