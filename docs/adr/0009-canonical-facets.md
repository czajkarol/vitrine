# 0009. A canonical facet vocabulary over AIC's raw terms

Status: Accepted
Date: 2026-09-04

**Postscript, 2026-09-04.** Every facet described below is derived from words a cataloguer
wrote. [ADR-0016](0016-inferred-facets-for-a-source-without-any.md) proposes a second origin — a facet inferred from the image itself, for a
source that has no such words — and the boundary between the two is load-bearing. An inferred
facet is stored apart, with its confidence and the model that produced it, and never merged into
`artwork_facets`: this table means "the museum said so", and it has to keep meaning that.

## Context

Explore filters on three vocabularies: artwork type, style and subject. Until now all three
were AIC's own values, shown to the user exactly as the museum catalogued them, and
deliberately left untranslated on the grounds that they were data rather than interface text.

Measured against the live index — 57,607 artworks, 84,190 style and subject tags — that
vocabulary is correct as cataloguing and unusable as a menu:

- **Duplicates.** `portrait` (1,612) and `portraits` (1,557) were two options. So were
  `landscape`/`landscapes`, `man`/`men`/`Male`, `blue`/`blue (color)`, `moche`/`mochica`,
  `andes`/`andean`, `19th century`/`nineteenth century`. `architecture` appeared three times,
  once as `architechture` — AIC's own typo.
- **The counts were wrong as well as the list.** Because those were separate options, the panel
  implied 3,169 portrait artworks. Deduplicated, there are 2,126.
- **Values that are not what the field says.** The third most common "subject" in the entire
  collection is `Collected by Hugh Edwards` (1,240) — provenance. `lundberg collection` (397)
  likewise. `photography`, `prints and drawings` and `decorative arts` are media and
  departments. `Gardner's Photographic Sketch Book` and `Crimea 1856` are publications.
- **Cataloguer's disambiguators.** `Japanese (culture or style)`, `roman (ancient, style or
  period)`, `coptic (historically identified as)`. Correct, and addressed to a colleague.
- **Inconsistent case.** `Arts of the Americas` beside `south american` and `early intermediate
  period`.

Two further things were true and pushed the same way. The filter list is capped at the most
populous values, and a cap that spends slots on duplicates offers less than it looks like it
does. And `frontend/CLAUDE.md` requires every user-visible string to come from `locales/`, which
AIC's English data could never satisfy while it was the museum's word rather than ours.

## Decision

A canonical facet layer, in `app/domain/vocabulary.py`, pure and with no I/O. It is the only
place the editorial judgement lives.

- A **facet** has a stable key (`style.japanese`), a group, an English label, and the raw AIC
  values it absorbs. The key is the API value, the saved preference, and the i18n key.
- Only **merges, relabels and drops** are written by hand. Every other raw value derives its own
  facet from itself, so the map stays short and nothing disappears without a line about it.
- **`DROPPED` carries a reason per value.** A vocabulary rots when things vanish from it
  silently.
- **Raw values are never destroyed.** `artwork_index.artwork_type` and `artwork_terms` keep
  AIC's own data forever. The facet layer is derived and rebuilt by `build_index.py --retag` in
  under two seconds with no network.
- **Storage is one table**, `artwork_facets` (migration 008), with artwork type folded in as
  `type.*`. Filtering, excluding and counting are then one query shape for all three groups
  instead of a column special case plus a join table.
- **Labels are ours, so they are translated.** `/api/filters` sends `{key, count, label}` and
  the frontend looks up `facet_style_japanese`, falling back to the English label the server
  sent. An untranslated facet degrades to English, never to a slug. English needs no facet keys
  in `locales/en.json` at all: the server's label is the English label, and duplicating it would
  give it two homes.

**How aggressive the folding is** was the owner's call, taken 2026-09-03: broad. Merge only the
unambiguous duplicates, drop only what is not a subject at all, and where a fold is a judgement
call about art, leave the values apart. So `andes` and `andean` merge and `south american` does
not; `moche` and `mochica` merge and the eleven Egyptian dynasties stay eleven facets. The
result is 30 type facets, 585 style and 1,611 subject, of which 26, 82 and 173 clear the
40-artwork offering threshold. `MAX_FILTER_OPTIONS` rose from 30 to 60 to match.

## Alternatives considered

**Show the museum's own words.** This is what the app did, and it is defensible: it is the
institution's vocabulary, it needs no maintenance, and it can never be accused of editorialising.
It loses because a filter list is a piece of interface, not a piece of the collection — and
because it was giving wrong numbers, which is not a matter of taste.

**Fold much harder, to 25–35 facets per group.** A list that reads at a glance. Rejected by the
owner: at that size a great many distinct things stop being individually selectable, and the
decisions doing the folding are opinions about art rather than corrections to data.

**A canonical top 30 with the raw long tail behind a "more" control.** Keeps everything reachable
and the list short. Rejected because it means two tiers in the panel and two code paths — raw and
canonical — for one question, in every place that filters, counts or excludes.

**Fix it in the crawler, storing only canonical values.** Cheaper: no second table, no `--retag`.
Rejected because the raw values are then gone, and every future change to the map would need
another 1,328-request walk of AIC. Keeping the raw data is what makes the vocabulary an edit to
one file.

## Consequences

- **The app now carries an editorial map, and it has to be maintained.** AIC's vocabulary drifts.
  `--retag` is the cheap half of that — one command, no network — and the expensive half is
  somebody noticing. `--retag` prints how many raw tags each group dropped, so a sudden change in
  that number is the signal.
- **Two facts learned building it, both worth keeping.** Stripping a parenthetical looks like
  cleaning up and is not: it merged `orange (color)` with `orange (fruit)`, and `edo (african)` —
  the Edo people of Nigeria — with `edo (japanese period)`. And a slug cannot be reversed into a
  label: `chimú` became the key `chim` and the label "Chim". Keys keep their parentheticals and
  fold accents; labels come from the raw values rather than from the keys.
- **Saved filters had to be cleared** by migration 008, because they held AIC's values and now
  hold facet keys. One-time, and the panel shows "Any" rather than an empty rotation.
- **A facet key is permanent once shipped.** It is what a preference stores. Renaming one silently
  clears somebody's filter.
- **What would make us revisit this:** if the map grows past the point where one person can hold
  the reasoning, it has stopped being a vocabulary and become a taxonomy, and a taxonomy belongs
  in data rather than in a Python module.
