# Product specification

vitrine is closer to a screensaver than to a web app. One artwork, dark background, no chrome
unless asked for. It is meant to run for hours on a second monitor and be glanced at.

If a feature would make it feel more like a dashboard, it does not belong.

---

## The display

- One artwork at a time, centred, aspect ratio preserved, `object-fit: contain`.
- Background is a **warm dark ground**, not near-black and not white. Near-black read as absence
  rather than as a room; a true ecru made the frame the brightest thing on screen and the
  artwork a hole in it. See Colour below.
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

Tint the page background with the artwork's dominant colour, heavily desaturated, and
transition it alongside the crossfade. It makes the letterboxing feel intentional rather
than empty.

**The ground is a warm dark wall, and it took four values in a browser to find.** It was
near-black until M17 and read as absence rather than as a room, which is what prompted the
change. A true ecru was tried next and is wrong for the opposite reason: it makes the frame
the brightest thing on screen, turns the artwork into a hole in it, and stops white caption
text being readable. A dark warm brown was muddy. A neutral grey at the right lightness was
legible and dead. What works is that lightness with the warmth left in — `hsl(hue 22% 33%)`,
the wall of a dimly lit gallery.

**The hue is the artwork's own, and that is the whole point.** The wall shifts with what is
hanging on it — cooler behind a blue print, umber behind a bronze. It is the one thing about
the ground that reads as deliberate rather than as a colour somebody picked, and it is why
this is set from the API field in `display.js` rather than written in CSS. Source it from the API `color` field, which is confirmed present and carries HSL
plus a population count (`docs/aic-api.md`). It is `null` on works without an image, so keep the
`lqip` derivation as the fallback for that case only.

The same field's `l` also picks the overlay scrim: above 60, the artwork gets a stronger one. **It is a hint, not a measurement, and the design must not depend on it.** AIC
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
← →        back and forward through what you have seen
F          toggle fullscreen
I          toggle metadata overlay
E          open or close the artwork's details
H          keep this artwork up five minutes longer
A          describe this artwork aloud
L          add to favourites, or remove
D          show me less like this, or take it back
X          hide this artwork — never show it again, in any mode
1 2 3 4 5  set interval to 30 sec / 1 / 5 / 15 / 30 min
S          toggle settings
?          the keyboard map, in the settings panel
Esc        close settings if open, else close overlay if open, else exit fullscreen
```

Plus three mouse gestures, and only three:

```
click the artwork          hide everything but the picture; click again for it back
double click the artwork   fullscreen on or off
click the caption          open or close the artwork's details
```

**A left click on the artwork** hides the overlay entirely, and movement does not bring it
back. A second click restores it.

**It works windowed as well as in fullscreen, and it says nothing.** Both of those were the
other way round until M17 and both were argued for here, so both amendments are worth stating.
It was fullscreen-only because windowed there is chrome around the page already and the gesture
would be a click that silently changed a mode — right about the silence, wrong about the
remedy, since the way out of the mode is the same click on the same spot that got you into it,
and requiring fullscreen first to reach the display's only gesture cost more than it saved. And
it used to name what had happened on the status line, on the reasoning that a click hiding every
control also hides the way back; it does not, and the message was chrome appearing at the top of
the screen at the moment the user had asked for less of it.

Clicks that land on the overlay's own buttons, on the caption, or in the settings panel are
not this. The caption taking the pointer for itself is what keeps the two click gestures
apart: they are told apart by where they land, not by what they do.

**A double click is fullscreen**, which every video player and every image viewer does and
this app did not — `F` was the only way in, and a key is not something anybody finds by using
a display with a mouse. The single-click gesture waits 250ms before acting so that the two
clicks of a double click do not hide the chrome and put it back on the way into fullscreen;
that delay is shorter than the fade it starts and is only felt on the single click.

**The overlay's controls say what they are on hover.** Six circles holding an arrow or a
heart are only as guessable as their icons, and the gear made a seventh. The words are the
`aria-label` each control already carried, so there is one string per control rather than
two. Not the browser's own `title` tooltip: it takes a second to arrive and arrives in the
operating system's styling, which is a grey box from another application landing on the
artwork.

`?` exists because thirteen shortcuts documented only in this file are thirteen shortcuts nobody
using the app knows about. It opens the settings panel with the keyboard map expanded, and the
map is translated like every other string.

Esc priority is exactly that order — most transient thing first. Shortcuts are disabled while
focus is inside a text input — except Esc itself, which always closes. The panel holds one text
field, the API key, and a field you cannot escape from is a panel you cannot close.

`S` **toggles** rather than only opening. In fullscreen the browser takes `Esc` for itself and
uses it to leave fullscreen, so a key that opens the panel and cannot close it leaves no
keyboard way out of the panel that does not also drop out of the one state this app is meant to
sit in. `QUESTIONS.md` #2, amended.

`H` extends the slot the artwork is currently in. Five minutes per press, up to an hour on
any one artwork, and the status line says the running total rather than the step — after three
presses "five more minutes" is the wrong number, and the one thing somebody holding an artwork
wants to know is how long they have. At the ceiling it says so, because a limit that is
indistinguishable from a broken key is a broken key.

**Only the current deadline moves.** Not the saved interval, not the session floor
`setFloorSeconds` puts under it, not the mode. So this is a duration rather than a state: there
is nothing to leave, nothing to remember to undo, and it cannot be left switched on. The hold
is spent when the artwork changes for any reason, including `Space`, so it never carries into
the next one.

**That is also how it satisfies the unattended rule.** This file has promised since M3 that a
display nobody is watching returns to rotating on its own. A "pin this artwork" would break
that promise; a hold released by an idle timer would keep it only by guessing whether anyone is
still in the room, and would release exactly when somebody walked off to make coffee — the case
they most likely wanted it held for. An extension ends by arithmetic instead: the deadline
arrives, and the display carries on. Nothing has to notice anything.

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

### The details, and expanding them

The description clamps to five lines. That is the resting state and does not change.

**The caption is the control.** Clicking anywhere in it — title, artist, date, description —
opens the details in place, bounded to 45vh and scrollable past that; clicking again closes
them. `E` does the same from the keyboard.

There was a small `i` button for this until M18, and there is not one now. The button had
already been argued into its final form here: shown on every artwork, because measuring the
clamp from `scrollHeight` made it vanish on the roughly seven artworks in eight with no
description, which reads as a rendering fault rather than as an absence. That was the right
fix for the wrong problem. A caption you click is a target the size of a caption rather than
of a 1.9rem circle, it needs no explaining, and it takes the app's only permanent piece of
overlay chrome off the screen. `QUESTIONS.md` #3, amended a third time.

What replaces the button is a line that appears on hover of the caption and nowhere else, so
the display at rest is unchanged — "click to read more" where there is a description, "click
for details" where there is not, "click to close" while it is open. It is `aria-hidden`: it
is an affordance for a pointer, and a screen reader is told about `E` in the keyboard map
instead. It is not rendered at all where there is no hover to leave.

It is a *details* toggle rather than an expand control. Where there is a description it opens
it; either way it opens the catalogue facts the overlay has no room for at rest — place of
origin, artwork type, reference number, and which collection the work is in. All four were
already on the response and were on screen nowhere.

Two clicks are ignored so that the gesture does not fight the others: the second click of a
double click, so a stray double click on the caption expands once rather than flickering back;
and a click that ends a text selection inside the caption or lands on the description's own
scrollbar, either of which would otherwise close the paragraph somebody is reading.

**Expanded is a different size**, because it is a different act. The whole panel steps up
together — a description that grew while its title stayed put would look like a fault — the
measure widens with it so the line length stays about the same count of words, and the
description brightens from `--fg-dim` to `--fg`. A size and a colour chosen for a caption
glanced at across a room are not right for four hundred words.

The scrim strengthens with it. The gradient is relative to the overlay's own box, so an overlay
expanded to most of the screen stretches the same gradient over 700px and stops being a scrim —
measured on a gilded triptych, where the title sat over gold leaf.

**The scrim is a column, not a bar across the frame.** The caption is left-aligned inside a
measure and never uses the right half of the screen, so darkening that half was hiding artwork
for nothing. Expanded it is the same shape, wider — which makes the change between the two
states a change of width rather than of shape. It cross-fades, and it has to be built as two
layers at different opacities to do that: a gradient does not interpolate into a different
gradient, so the old approach of swapping the gradient's numbers was a step change across most
of the screen.

That old approach drove the vertical gradient almost to opaque when the details opened. It
worked, and it blacked out the entire frame to read one paragraph — the wrong trade on a
display whose whole job is the picture.

**Nothing on the display outlasts the mouse, including the pointer itself.** It hides after six
seconds of stillness and returns on any movement or press. Slower than the overlay's own 3.5s,
because a cursor that vanishes while somebody is still deciding where to click is a different
kind of annoyance — and never while the settings panel is open, where they may be reading a
form rather than aiming at anything.

Expansion is per artwork and temporary. It collapses when the artwork rotates, on `Esc`, and
when the overlay fades. While it is open **the rotation is held** and the idle fade stretches
from 3.5s to 20s. Those were two halves of the same problem and only one of them had been
solved: text staying put while the picture underneath it changes is no better than the text
going away. Scrolling the description counts as activity for the same reason.

The hold ends when the expansion does, which includes the overlay fading after 20s of
stillness — so an unattended display still returns to the artwork and starts rotating again on
its own, which is what the original ruling protects. Holding the clock is a promise to somebody
who is *reading*, not a way to stop the display.

`I` keeps its own meaning — pin or unpin the whole overlay. Two affordances, two meanings.

### Controls on the display

Six buttons, plus the caption itself, and they are the only clickable controls outside the
settings panel: back, next, like, dislike, never again, settings, and — when a provider can
write one — describe aloud. They live inside the overlay, which is hidden at rest, so "no
visible controls at rest" is unaffected.

**The gear is the last of them and is set apart from the rest**, because it is the one control
there that is not about the artwork on screen. It exists because `S` is not an affordance:
somebody who had only ever used the mouse had no way to find out from the screen that the app
had settings at all.

**"Never show this again" has a button now, and it takes two clicks.** This file refused it
outright until M18 — "not a thing to put one click away from a cursor" — and the reasoning was
sound: the artwork leaves the screen the moment the verdict lands, so a mis-click is a
permanent decision the user cannot see well enough to undo. What was wrong was the conclusion.
The answer to an irreversible control is a confirm step, not no control, and no control left
the one verdict that changes the collection most reachable only by a key nobody had been told
about. So the first click arms it — the button turns, and both the label and the status line
say what the next click does — and it forgets after four seconds. `X` stays a single press: a
key nobody hits by accident does not need the guard.

The overlay itself keeps `pointer-events: none` so it cannot swallow the movement that reveals
it; the buttons, the caption, the expanded description and the accessibility section take the
pointer back one element at a time.

---

## Sources

Two museums, chosen in the settings panel. See ADR-0013.

**The Art Institute of Chicago** is the indexed one and everything above applies to it.

**The Cleveland Museum of Art** is fetched live, one request per artwork, and is deliberately a
much smaller feature: Random only, one filter — its own artwork types, in its own vocabulary,
with counts asked of the museum. Curated and "For you" rank against a score only the local index
carries, so they are disabled while Cleveland is selected, with a line in the panel saying why.

Three things degrade on a Cleveland artwork and each has a defined fallback, because "it looks
slightly worse and nobody wrote it down" is the failure to avoid. There is no `lqip`, so the
crossfade starts from the previous artwork rather than from a blur. There is no `color`, so the
overlay uses its default scrim — which is strong enough alone, as M8 established. And there is
no `alt_text`, which is what grounds both AI prompts, so **the AI features are not offered on a
Cleveland artwork at all**; the controls are hidden rather than offered and then refused.

There is also no IIIF service — three fixed image URLs per record, one of them a TIFF — so the
width ladder and the ADR-0008 proxy fallback are skipped and the URL is used as sent.

Switching source clears the filters as well as the history. The two vocabularies have nothing in
common, so carrying a selection across would show a filter that silently matches nothing.

Attribution is per artwork rather than per app, because it is a licence condition rather than a
label. Cleveland's metadata and images are CC0; the Art Institute's CC BY 4.0 clause stays on
its own half, where it applies.

### Filters on a source that was never catalogued for them

**Cleveland offers one filter where the Art Institute offers three, and that is a metadata gap
rather than a missing feature.** Every facet vitrine has comes from words a cataloguer wrote,
and Cleveland does not publish anything that maps onto style or subject. ADR-0013 accepted this
by not indexing the source; ADR-0016 proposes closing it by inferring the facets from the images
themselves, trained on the Art Institute's own 131,264 facet rows.

Nothing of this is built. Four rules would govern it if it were, and they are the decision:

- **Only above a floor measured per facet.** `type.painting` is visible in a picture;
  `style.chimu` is cataloguer's knowledge no amount of looking recovers. Each facet gets the
  threshold that buys a stated precision on a held-out slice of AIC, and a facet that never
  reaches it is not offered for that source at all.
- **Below the floor is no facet, not a guess.** The artwork carries nothing and does not appear
  under that filter. Showing fewer results is a narrowing the user can see; a confident wrong
  tag is a filter quietly lying, which is the failure this whole section exists to prevent.
- **An inferred facet says it is inferred**, in the panel and on the artwork, and is stored with
  its confidence and its model version — never merged into `artwork_facets`, which means "the
  museum said so" and has to keep meaning that.
- **A model looks at the picture here, and it must say so.** The spoken description (M14,
  ADR-0015) promises the opposite — no model sees the artwork, the words are the museum's own —
  and that promise stays exactly true. These are two features with opposite properties and the
  new one does not get to inherit the old one's reassurance.

The cost is not the model. Filtering means knowing a candidate's facets before choosing it, so
Cleveland would have to be indexed — which is the thing ADR-0013 deliberately did not do.

## Modes

### Explore

The user picks filters and gets random artworks matching them. Build filter options from what
the index actually contains, not from a hardcoded list — a hardcoded list will drift from what
the API supports and produce empty result sets.

Only expose a filter if the local index has enough artworks behind it to sustain rotation.
A filter that yields four artworks is worse than no filter. Show the count.

**Two things are excluded before anybody asks: coins and medals.** A fresh install starts with
`type.coin` and `type.medals` in its exclusion list — 1,220 and 418 of the 57,607 indexed works.
They are the same case twice: small, dark, two-sided, photographed identically against the same
grey card, and one arriving every few minutes is what an ambient display of art is least served
by. A museum has reason to catalogue them apart; on a wall they are one thing. Nothing else
meets that bar, and the list is meant to stay this short: adding to it is hiding something from
somebody who never asked.

**It is a default, and it has to arrive looking like one.** It is seeded into the `exclude`
*preference* on first run, not compiled into the query, so it comes into the panel as an
ordinary exclusion — the artwork-type badge reads "2 out", the group opens itself because
something in it is set, the Coin and Medals rows are struck through, and one click each clears
them for good. A constant in the selection path would remove 1,638 artworks with nothing on
screen saying so,
which is the failure this whole section is written against. Scoring was the other candidate and
is the wrong tool: it ranks Curated and does nothing in Random, so "excluded by default" would
not be true in the mode most people are in.

The seed applies only when the `exclude` row has never been written, which on this table means
no preference has ever been saved — a `PUT` writes every key at once. A saved empty list is a
decision and outranks the default; without that distinction, clearing the exclusion would undo
itself on the next reload. `domain/vocabulary.py` holds the list and the reason.

Filter on `artwork_type_title`, the vocabulary behind `/artwork-types`. Do **not** filter on
AIC's `classification_title`, which sounds like the same thing and is not — it is closer to a
medium (`oil on canvas`). See the table in `docs/aic-api.md`.

Style and subject (`style_titles`, `subject_titles`) are filters too, added in M3.5. They differ
from artwork type in one way that shows in the UI: type is a closed vocabulary and all of it can
be offered, while style and subject run to hundreds of facets, so only the most populous sixty
are — on top of the same "enough behind it" rule. A group with nothing to offer is hidden rather
than shown empty.

The three groups combine with AND. **Inside a group, several values combine with OR** — see
"One control per facet" below, and ADR-0014. The original rule here was radio buttons on the
reasoning that "landscape **and** portraits" narrows to almost nothing, which is true and is an
argument about the *operator* rather than about how many values a group may hold. ANDing two
artwork types is not merely narrow, it is empty by construction: nothing is both a painting and
a print. ORing them is what anybody means by ticking two boxes, and it is not narrow at all.

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

#### One control per facet

A facet has three states with respect to a filter, so its control has three. One button per
facet, cycling **off → include → exclude → off**, one list per group. Until M13 there were two
controls per vocabulary — a list of radios for inclusion and a collapsed second list of
checkboxes for exclusion — which meant the sixty style facets appeared twice in the panel, in
two lists, meaning two different things, and ruling one out meant finding it a second time
further down.

The state is carried three ways at once, deliberately: a glyph (`✓` / `✕` / nothing), a colour,
and a word in the `aria-label`. Any one alone is a guess — the glyph is `aria-hidden`, and
green-versus-red is the worst possible colour pair for the people most likely to be excluded by
it.

Groups collapse. A collapsed group carries a badge in its heading saying what is on inside it,
and opens itself when something is set, so a live filter can never be hidden behind a heading
somebody has to remember to check. A group with more than twelve options gets a search box; a
selected row always shows regardless of the search text, because hiding a selection makes it
invisible rather than absent. An excluded facet shows no count — it is always zero, and a
struck-through row with a `0` beside it reads as a broken filter rather than a working one.

Including and excluding the same facet is contradictory rather than empty, and returns the usual
"nothing matches those filters" — never a silently dropped exclusion.

Inclusion and exclusion are sanitised differently on the way in, and the asymmetry is the point:
an exclusion that cannot be parsed is dropped, because that shows the user *more* than they
asked for and they can see it; an inclusion that cannot be parsed is **kept**, matches nothing,
and the display says nothing matched. A dropped inclusion would be a filter that silently
stopped filtering, which is the one failure this whole section is written to avoid.

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

#### Saved filters

A combination worth returning to can be saved under a name and put back with one click.
A saved combination is a **museum plus the three inclusion lists plus the exclusion list** —
exactly what the panel already assembles — and deliberately nothing else. Not the mode and
not the interval: those are how the display behaves rather than what it is showing, and a
name that quietly changed the rotation speed would be a surprise filed under the wrong
heading.

**Naming.** The user types one, and the field is pre-filled with the labels of the first
three chosen facets ("Print, Japanese, Men") so that saving is one action for somebody who
does not want to invent a name. It is a placeholder and not a value: it never has to be
cleared, and it never overwrites a name somebody is halfway through typing. Names are
unique, and saving over one replaces it — re-saving a preset you have just adjusted is the
ordinary case, not a conflict to report. Thirty is the cap, which bounds a list somebody
has to read rather than any storage; a replacement is never refused by it.

**A preset whose facets no longer exist is kept, applied, and reported.** A saved key can
stop being offered — a rebuilt index, a change to the merge rules in `domain/vocabulary.py`,
a different museum. Nothing drops it: not the table, not the route, not the panel. Dropping
an inclusion would quietly *widen* what the preset means, turning "Japanese prints" into
"prints", and a filter that silently stops filtering is the one failure this whole section
is written against — `_included_facets` takes the same position for the same reason. So it
is applied exactly as saved, matches nothing, and the panel says how many of the preset's
filters the index no longer offers. A preset that has stopped meaning what its name says is
worse than one that says it has.

They live in their own table, `filter_presets`. `preferences` is single-valued by design —
one string per key, and the typed shape at the API boundary exists to keep it that way —
while a preset is plural, has an identity and a name, is listed and deleted individually,
and a JSON blob holding all of them would be rewritten in full on every save. Every other
plural thing this app remembers is already a table. Being a new table also keeps them out
of a published export for free: `repositories/corpus.py` copies an allow-list of corpus
tables into a fresh file, so personal data is excluded by not being named (ADR-0011).

**No ADR for this, and that is the finding rather than an omission.** Every hard call it
makes was already taken somewhere else: the facet encoding by ADR-0014, staying out of the
export by ADR-0011, and the stale-facet stance by the rule above, which predates presets.
What is left is a table, a small repository, three routes and a list of buttons. An ADR
here would record a decision nobody made.

### Curated

Transparent weighted scoring over the local index. Signals, all of which come from real API
data:

| Signal | Rationale |
|---|---|
| `is_boosted` | AIC's own essentials selection |
| Source resolution | `thumbnail.width/height`; bigger originals look better full-bleed |
| Aspect ratio | Closeness to the viewport ratio; less letterboxing |
| Metadata completeness | Artist, date, medium, description present |
| Has `alt_text` | Correlates with curatorial attention |
| Artwork type | Paintings and photographs display better than furniture or documents |
| Recency penalty | Seen in the last N artworks |

**Machine learning is no longer ruled out of this app, and Curated is not where it is wanted.**
ADR-0006 banned it outright; ADR-0016 lifted the ban in M17 for a different purpose entirely —
see Sources below. The score stays a weighted sum of the signals in that table, with `--explain`
behind it, and nothing about it changes.

### For you

A third mode, and deliberately not a change to Curated — see ADR-0010.

`L`, `D` and `X` are the entire input. No dwell time, no skips, no inference from silence: an
ambient display is left running in an empty room, and "watched for nine minutes" usually means
nobody was there.

**Three verdicts, and the middle one is the point.** `L` and `X` are the two ends of a scale
with nothing between them: `X` is a hard exclusion, so it could never also mean "less of this".
`D` is that middle — a ranking signal and nothing else, and the artwork stays in the rotation.
Because the nudge is all the user gets for pressing it, a dislike counts against the profile
harder than a hide does; hiding is usually about one artwork rather than a category, and its
real force is the exclusion. Pressing the same key twice takes the verdict back.

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

Two different things share the word, and they are not the same feature.

**The repeat penalty.** Keep the last ~50 artwork IDs in SQLite. Use it to avoid near-term
repeats, as a soft penalty in scoring rather than a hard exclusion. An artwork seen two hours ago
should be unlikely, not impossible.

**Going back.** The display also keeps the last twenty artworks it has shown, in the browser, and
`←` and `→` walk them. This is not the SQLite table: that one holds ids so a query can penalise
them, and re-fetching an artwork by id to redisplay it would be a second endpoint answering a
question the browser already knows the answer to.

It stores payloads rather than decoded images — a decoded 1686px bitmap is several megabytes and
this app runs for hours — and the image is requested again on the way back, where the browser's
own HTTP cache normally answers instantly. It lives only as long as the page, which is the right
lifetime: "the one before" is a question about the last few minutes, and a stack restored across
a reload would offer to return to something nobody remembers seeing.

Moving through it re-arms the rotation clock, the same way a manual advance does. Going back to
look at something and having it rotate away two seconds later is the opposite of the point. It is
cleared when the source changes, because a stack crossing museums would offer to return to an
artwork the current source cannot show — and the two id spaces overlap.

---

## Ambient mode

Keeps the screen awake while the app is displaying. Use the **Screen Wake Lock API**:
`navigator.wakeLock.request('screen')`. It requires a secure context, so localhost is fine.

Re-acquire the lock on `visibilitychange`, because browsers release it when the tab is hidden.
Handle the API being unavailable by hiding the toggle, not by erroring.

Do not write OS-level power management. Do not simulate input of any kind. This is a
display feature and the README describes it as one.

**Off by default, except that going fullscreen turns it on.** The argument for off — that
keeping somebody's screen awake is a side effect on their machine rather than a default — held
while the app was a window among other windows, and it does not hold in fullscreen. Fullscreen
*is* the ask: it is the one mode this app was built for, and a display that blanks ten minutes
into it is the exact failure the wake lock exists to prevent. So entering fullscreen sets
`ambient` to true and requests the lock. That argument was a comment on `PreferencesResponse`
rather than a line in this file; it is amended in place there and stated here. M17.

Three things that rule must not do, and they are the whole of its difficulty:

- **It must not overrule somebody who turned ambient off by hand.** A stored `false` cannot
  say on its own whether it means "never thought about it" or "no" — every save writes every
  field — so the deliberateness is recorded separately, in `ambient_by_hand`. Nothing in the UI
  shows that preference; it exists only so this rule can tell the two cases apart.
- **It must not touch the preference where there is no Screen Wake Lock API.** The toggle is
  removed from the panel outright there, so writing `ambient: true` would save a setting the
  user can neither see nor undo.
- **It must not say the screen will stay awake unless a lock is actually held.** The request is
  refused while the document is hidden and on some machines on battery, and enabling ambient
  mode swallows that by design. The line the display flashes is conditional on a lock having
  been acquired, not on the preference having been set. Ask `isHolding()`, not `isEnabled()`.

Leaving fullscreen does not turn it back off. By then it is the user's saved preference, shown
in the panel and undoable there; taking it away again would be a second change they did not ask
for. It is entered on `fullscreenchange` rather than on the app's own `F`, because F11 is
fullscreen too and never goes through the app's toggle.

---

## Settings

A small panel, not a page. Source, mode, interval, filters, ambient mode, AI provider and key,
language, and the keyboard map. Persisted locally. Opening settings pauses rotation; closing
resumes.

**Two tabs since M18**, and the split is one cut — everything about what the display shows,
and the AI provider:

1. Source
2. Mode
3. Rotation
4. Ambient
5. Filters
6. Saved filter sets
7. Language

and, behind the second tab, the AI provider and key. It was three tabs for a day, with the
filters behind one of them. They are the control reached for most often here, a tab is the
wrong place for that, and everything above them is now compact enough that they are on the
first page without scrolling. What is left behind a tab is the one control here that is not a
preference: a secret.

The keyboard map and the Esc hint stay below the tabs, because neither is a setting and `?`
opens the map from anywhere. Which tab is showing is remembered for the life of the page and
not persisted: coming back to the tab you were last in is worth having inside a session, while
a *saved* tab means the panel opens on the API key months later because that is where you once
were.

There is no arrow-key roving between the tabs, which is what the ARIA practices ask for. The
arrow keys belong to the history stack in this app and would do both things at once, so both
tabs are in the tab order instead.

**A scale of a handful of values is a row.** Rotation, mode and language are segmented rows
rather than stacks of radios — five, three and two lines of dot-plus-label to offer five, three
and two choices was most of the panel's height. They are still radios: the input is hidden from
view rather than removed, so each group keeps its keyboard behaviour and a screen reader still
hears the options with one chosen.

**Mode explains the mode you are in, not all three at once.** One line under the row saying what
the selected mode does, and one disclosure under that holding the long version — Curated's
weights, or how "For you" is built. It was three stacked radios each carrying its own hint plus
a separate disclosure for Curated: five lines and a triangle to offer three choices. Random has
nothing to open, so on Random no triangle is offered at all.

**"For you" says how it works, and every claim in it is a line in `app/domain/affinity.py`.**
It re-ranks the Curated picks rather than replacing them, at most roughly doubling a score; it
counts the facets of the favourites, weighting subject over style over artwork type; and only
explicit presses count — likes, dislikes and hides, nothing read from what was skipped or how
long anything was looked at. The visible line above it says whether it is personalising *yet*,
because below the threshold it is serving Curated picks and saying otherwise would be the kind
of small lie that makes a panel untrustworthy.

**The saved-filter group is named for the act, not the noun.** "Saved filters" sitting under a
group called "Filters" read as a second list of filters rather than as a way to keep the first
one; it is "saved filter sets" now, and the line under it says what to do — name the filters
above to bring them back later.

**It is still a form, and it no longer reads as a form bolted onto an ambient display.** The
panel is set in the museum's face, not the interface sans — the two-voices rule exists so
generated text is never mistaken for a caption, and nothing in this panel is a caption. In the
system sans it read as a settings dialog that happened to be open in front of a painting.
Garamond has a small x-height, so everything here is a step larger than the sans equivalent
would be; counts, badges, the small asides and the API key field stay in the sans, the last of
those because a key is a code string.

Section names are sentence case in that face. Small tracked-out capitals are the house style of
a settings dialog, which is the thing this panel is trying not to be, and they needed a wide
gap under them to stop the capitals crowding the first row.

**The tabs are the loudest thing in the panel, deliberately.** The first attempt made them
small, dim, tracked-out capitals — quiet, consistent with everything else, and unreadable as
navigation: the AI tab may as well not have existed, and the AI settings were reported missing
from a panel that was showing them one click away. They are now the size of the text they
switch, in a tray with a ground of its own, with the selected one filled. Quiet is right for
the rest of the panel and was wrong for the one control that says what else is in it.

**A scale of short values is a row, not a stack.** The five rotation intervals were five lines
with a radio dot each — a sixth of the panel's height to say five things whose labels are three
characters long. They are a segmented row now, built like the tab tray because they are the
same kind of control, and still radios underneath: the input is hidden from view rather than
removed, so the group keeps its keyboard behaviour and a screen reader still hears five options
with one chosen.

**Filter groups look like rows you open**, because they were not read as clickable at all: text
at two steps below the panel's size, with no marker — `display: flex` drops the disclosure
triangle — sitting flush against the panel's other labels. They now carry a chevron that turns,
a hairline under each, a ground on hover, and facet rows at the panel's own size.

The group separators are drawn in the margin rather than as each fieldset's own border. A
`<legend>` is laid out over the fieldset's top edge rather than inside its content box, so
`padding-top` on the group opened its gap *under* the section name instead of above it — which
is where most of the panel's empty space was coming from — and a `border-top` gets notched for
the legend, so the rule runs through the word rather than above it.

**No emoji on the filter names.** They were considered and are the wrong instrument here twice
over. On the three group headings they would be decoration that carries no information; on the
facets themselves — sixty of them, across style, subject and artwork type — any glyph for
`style.islamic` or `subject.religion` is a picture standing in for a culture, which is exactly
the forced association to avoid. The panel's hierarchy is doing that work with type instead.

**Every explanation longer than a line is behind a triangle**, and the panel opens onto controls
rather than onto prose: how Curated ranks, how the three-state filter rows work, and where the
API key is kept. What stays in the open is a line at most — the mode and source definitions,
which are what a mode called "Curated" needs in order to mean anything, and the indexed count.

API keys entered here are write-only in the UI — once saved, show `…abcd`, never the value.
The panel also says where the key is kept: the OS keyring, or unencrypted in the app's own
database when there is no keyring to use.

**The long form of that is collapsed, and the one-line version is the summary.** Two paragraphs
about key storage in front of somebody every time they open the panel is more than most people
want; a disclosure whose summary is a *label* would hide the thing the UI is required to say.
So the summary is the fact — "kept in your computer's own password store", or "kept unencrypted
in vitrine's own file" — and the paragraphs behind it are the why and what to do about it. The
fact is on screen before anything is typed, not after, because it is what someone needs in
order to decide whether to type at all.

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

Keyboard reachable throughout — including the overlay's buttons, which are real `<button>`
elements in the tab order, and which leave the tab order with the overlay when it fades.
`alt` text from `thumbnail.alt_text`. Sufficient contrast on the overlay. Honour
`prefers-reduced-motion` by cutting instead of crossfading.

### Described for listening

`A` asks for a spoken visual description of the artwork on screen, and reads it aloud. It has
its own labelled region below the interpretation — `role="region"` with a name, `aria-live`, and
real buttons — because a listener needs to be able to find it, not merely to have it exist.

**The description is written from the museum's own words, and the display says so.** No model
sees the image: everything visual comes from `thumbnail.alt_text`, which a person at the Art
Institute wrote while looking at the artwork. Every screen showing a description also shows which
field it came from and the sentence "No AI has seen the artwork itself."

That line is the feature's honesty, not a disclaimer attached to it. Everywhere else in this app
a wrong generated sentence is recoverable, because the artwork is on screen disagreeing with it.
Here the reader is the one person who cannot check. So the prompt's strongest rules are about
restraint — take everything visual from the museum's text, and *match the length of your source*,
because padding a one-clause alt text is inventing and a listener cannot tell the difference —
and an artwork with no visual metadata at all is refused rather than described. ADR-0015.

Playback is the browser's own speech synthesis. It costs nothing, needs no key and works
offline, which matters more here than voice quality does. **Replaying is free and is its own
control**: the text is on screen and the server has it cached, so hearing it again is not a
second request and not a second bill.

Asking for a description holds the rotation at five minutes or slower for the rest of the
session, without changing the interval the user chose. A description takes most of a minute to
hear, and at the 30-second rung the artwork would be gone before the end of it. The user's own
setting comes back when the floor lifts.

The feature is offered only where a configured provider can actually produce one — `/api/health`
reports the capability and the control is hidden otherwise. A control that is offered and then
refuses is worse than one that is not offered.
