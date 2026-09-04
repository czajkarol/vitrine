# 0014. One tri-state control per facet, and OR inside a group

Status: Accepted
Date: 2026-09-04

## Context

Until M13 the Explore panel had two controls per vocabulary. Inclusion was a list of radio
buttons — one value per group, ANDed across the three groups. Exclusion was a second, collapsed
list of checkboxes under it, multi-valued and NOT-ed. So the sixty style facets appeared twice
in the panel, in two lists, meaning two different things, and ruling one out meant finding it a
second time further down.

The radios were not an accident. `docs/product-spec.md` argued for them, and the argument was:

> "Landscape **and** portraits" narrows to almost nothing and reads as a bug rather than as a
> filter, so the panel offers radio buttons and not checkboxes.

That is true, and it is an argument about the **operator**, not about the arity. `type.painting
AND type.print` is not merely narrow, it is empty by construction — nothing is both. The filter
anybody means by ticking two boxes in one group is OR, and OR inside a group is not narrow at
all: painting-or-print is 26,120 indexed artworks where painting alone is 1,816.

The owner asked for two things that turn out to be the same thing:

> Combine include/exclude into one intuitive filter UI. Allow multiple simultaneous filters
> across fields.

## Decision

**A facet has three states with respect to a filter, so its control has three states.** One
button per facet, cycling off → include → exclude → off. One list per group instead of two.

**Inside a group the operator is OR; between groups it stays AND; exclusion is NOT over all of
them at once.** `_facet_clauses` in `repositories/artwork_index.py` takes one alternative-set per
group and emits `id IN (SELECT ... WHERE facet IN (...))` per group, ANDed, plus a single
`NOT IN` over everything excluded.

The product-spec's reasoning survives the change intact, narrowed to what it was actually about:
combining *across* groups with AND is right, and "a Japanese print" narrows the way a person
expects. Only the sentence concluding "radio buttons and not checkboxes" is reversed.

The state is carried three ways at once, deliberately: a glyph (`✓` / `✕` / nothing), a colour,
and a word in the `aria-label` (`filter_state_include` and friends). Any one of those alone is a
guess — the glyph is `aria-hidden`, colour excludes a good number of the people this app is for,
and green-versus-red is the worst possible pair for that.

Three smaller consequences fall out and are part of the decision:

- **Groups collapse, and carry a badge saying what is on inside them.** With six lists gone and
  three left, the panel could show them open; with a badge and auto-opening when something is
  set, a collapsed group can never hide a live filter.
- **A group longer than twelve options gets a search box.** Sixty facets is a list nobody scans.
  A selected row always shows regardless of the search text, because hiding a selection makes it
  invisible rather than absent.
- **Inclusion and exclusion sanitise differently.** `_valid_facets` drops anything that is not a
  well-formed facet key; `_included_facets` keeps it. The two halves are not symmetric: a dropped
  exclusion shows the user *more* than they asked for, which they can see and correct, while a
  dropped inclusion silently stops filtering — a filter ceasing to be a filter, which is the one
  failure the whole Explore path is written to avoid. An unrecognised inclusion is kept, matches
  no row, and the display says nothing matched.

## Alternatives considered

**Keep radios, add checkboxes beside them.** Four controls per facet. Rejected without much
thought; the problem was already too many controls.

**Checkboxes for inclusion, keep the separate exclude list.** Solves the multi-select half and
none of the "one control" half. The exclude list was the part that made the panel hard to use:
it was collapsed, it was a second copy of the same sixty labels, and nothing on screen connected
a row in one list to the same row in the other.

**Three-way select or a segmented control per row.** More conventional, and much wider — sixty
rows of three-segment controls is a wall. The cycling button is one tap target and reads at the
density a list of sixty needs.

**Right-click, or shift-click, to exclude.** Discoverable by nobody, and unavailable from a
keyboard without inventing a second binding. Cycling is discoverable from the hint line above
the groups, which is one sentence.

**Leave the operator as AND and just allow several.** This is the version that would have made
the product-spec's original sentence true: it really would narrow to nothing. Rejected as
obviously broken the moment it is used.

## Consequences

- **`artwork_type`, `style` and `subject` are repeatable query parameters and lists in
  `preferences`.** They are comma-joined in the `preferences` table, the encoding `exclude` has
  always used and safe for the same reason: a facet key is `[a-z0-9.-]` by construction and can
  never contain a comma. A value written by an older version holds one key and decodes to a
  one-item list, so no saved filter was lost.
- **The dependent counts still work and now mean slightly more.** Choosing a second style raises
  the type counts rather than lowering them, which is what OR should look like from outside.
- **An excluded facet shows no count.** It is always zero, and a struck-through row with a `0`
  beside it reads as a broken filter rather than as a working one.
- **`filters.js` is a new module.** `panel.js` was already the largest file in the frontend and
  the group logic is self-contained. The panel keeps the orchestration: which groups exist, what
  the selection is, and telling the display when it changed.
- **The group's name in the markup and its facet namespace are different strings for one of the
  three** — `artwork-type` versus `type.` — and code that matched the shared exclusion list on
  the wrong one silently dropped every exclusion in that group. Found by the Playwright flow
  written for this control, on its first run. The namespace is now carried explicitly.
- **Three states is a property of the source, not of the control.** Exclusion is a NOT over the
  canonical facet layer and only the indexed corpus has one, so on a live source the cycle is
  two states: off → include → off (ADR-0013). It was three there for two milestones, and the
  third click produced a state the server rejected and the next redraw dropped — a control with
  a state that silently did nothing, which is the failure this whole panel is written to avoid.
  The group is told whether its source can exclude, and the sentence above the groups says which
  cycle is running. Amended M17.
- **Every click re-asks for the counts, and the answers race.** The counts are dependent, so a
  changed selection means a new `/api/filters`; nothing sequenced those requests, and an
  exclusion is a NOT over the whole facet table and is reliably the slower query. So the answer
  saying "excluded" could land *after* the answer to the click that cleared it, and the panel
  drew the stale one. A count of zero on a row whose state had just gone back to `off` is
  exactly the pair the row disables — the facet went inert and could not be turned back on.
  Requests are numbered now and an answer that is not the newest is dropped. Amended M17.
- **What would make us revisit this:** somebody wanting AND *within* a group — "tagged both
  landscape and winter" — which is a real query the subject vocabulary could support and which
  this design has no room for. It would need a fourth state or a per-group operator toggle, and
  neither is worth it until someone asks.
