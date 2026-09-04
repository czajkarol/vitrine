# 0013. Cleveland as a live source, and the seven-eighths of ADR-0012 we did not pay

Status: Accepted
Date: 2026-09-04

Supersedes the decision in [ADR-0012](0012-additional-art-sources.md); its research stands and
is the reason this record can be short.

## Context

ADR-0012 recommended against a second art source and priced the recommendation: eight things a
second source costs, of which one is an API client. The owner has since asked for Cleveland
anyway, with three constraints that change the arithmetic rather than dispute it:

> Add Cleveland as a separate artwork source/provider. Make the source selectable. Implement
> only basic artwork display + simplest useful filters. Do not aim for AIC feature parity yet.
> Keep the provider abstraction clean for future expansion. Do not overengineer this stage.

"Do not aim for parity" is the whole decision. ADR-0012's eight items are the cost of a second
*indexed, scored, faceted* source. Most of them are consequences of indexing, not of having two
museums, and a source that is never indexed does not incur them.

The measurements in ADR-0012 were re-checked against the live API on 2026-09-04 before any code
was written, and all of them held: 41,512 CC0 records with an image, no API key, no published
rate limit, `skip` pages the whole set, `info.total` is a real count for whatever parameters
were sent, and there is no IIIF service — `images.web` (900px on the long edge), `images.print`
(3400px) and `images.full` (a TIFF browsers do not render).

## Decision

**Cleveland is a live source. It is never indexed, never scored and never faceted.**

One request gives one artwork. `providers/source.py` defines `ArtworkSource` — deliberately
small, because it is the interface for a *live* source and the Art Institute does not implement
it. AIC is indexed, scored, faceted and served out of SQLite, and everything about that is a
much larger surface than any second museum is worth. A live source answers two questions: give
me one artwork, and what may I filter on.

Against ADR-0012's eight items:

| # | ADR-0012 said it costs | What we did |
|---|---|---|
| 1 | `artwork_index` needs a `source` column and a composite key, touching every read path | **Paid, in one table only.** Nothing is indexed, so `artwork_index` is untouched. But artwork id 1 is a real record at both museums, and a favourite keyed on `artwork_id` alone would let a Cleveland print un-like an Art Institute painting — so `artwork_feedback` gained `museum` and a composite key. Migration 010. |
| 2 | The IIIF base stops being one remembered value | **Paid.** `SourceArtwork` carries either a `iiif_base` or a finished `image_url`, and the response carries whichever applies. The remembered base is left alone by a source that has none. |
| 3 | `chooseWidth()` has nothing to choose from | **Accepted.** `loadImage()` takes `image_url` as-is and skips the width ladder and the ADR-0008 proxy entirely. One usable size, `web`; `print` is several megabytes and slow to first paint on a display that changes picture every few minutes. |
| 4 | Three display features degrade | **Accepted, and written down** — see Consequences. |
| 5 | Curated scoring is calibrated on AIC's fields | **Dodged.** Cleveland is not scored, so nothing compares a Cleveland score to an AIC one. Curated and "For you" are disabled while a live source is selected, with a line in the panel saying why. |
| 6 | The facet vocabulary is a hand-written map of AIC's terms | **Dodged.** No canonical facets. One closed list of ten artwork types, in Cleveland's own vocabulary, with counts asked of the museum rather than derived. |
| 7 | The attribution becomes per-artwork | **Paid.** `attribution_aic` / `attribution_cma` in both locales, chosen from `artwork.museum`. The CC BY clause for the `description` field stays on the Art Institute's half, where the licence actually applies. |
| 8 | The export gains a dimension | **Dodged.** The export is the corpus, the corpus is the index, and Cleveland is not in it. `repositories/corpus.py`'s allow-list is unchanged and still correct. |

So: three paid, three dodged by not indexing, one accepted as degradation, one accepted as a
narrower feature. That is a much smaller bill than ADR-0012 quoted, and ADR-0012 was not wrong —
it priced a different thing.

**The AI features are not offered on a Cleveland artwork.** ADR-0012 called this out as a
decision that would have to be taken out loud rather than arrived at by accident, so here it is,
out loud. Two independent reasons agree: the server can only find metadata for an artwork it can
look up — the index, the bundled set, or AIC — and a live Cleveland record is in none of the
three; and Cleveland has no `alt_text`, which is what grounds both prompts. `CLAUDE.md` puts the
museum's own visual description at the centre of the AI path deliberately, and a source without
one needs a different prompt or no AI at all. It gets no AI. The controls are hidden rather than
offered and then refused (`canInterpret()` in `frontend/js/main.js`).

## Alternatives considered

**Index Cleveland too, and pay all eight.** Rejected on the owner's constraint and on the
arithmetic: 41,512 records at Cleveland's own pace is another long walk, and items 5 and 6 are
the expensive ones — recalibrating the scoring weights against a second museum's fields, and
hand-mapping a second vocabulary into `domain/vocabulary.py`. Neither buys anything until
somebody wants Curated across both collections, and nobody has asked for that.

**Make AIC implement `ArtworkSource` too, for symmetry.** Rejected. It would be an interface
that describes the smaller of the two things AIC does and hides the larger, and every caller
would have to know which of the two paths it was on anyway. `SelectionService` branches once, at
the top of `next_artwork`, which is honest about there being two different mechanisms.

**Fall through to the Art Institute when Cleveland is down.** Rejected explicitly. The user
chose a museum; quietly showing them a different one is what makes a source selector
untrustworthy. A live source that cannot answer leaves the artwork already on screen where it
is and the clock backs off, which is what the display already does when AIC is unreachable.

**Offer Cleveland's `description` to the AI path even without `alt_text`.** Tempting, because
Cleveland's descriptions are good and are on more records proportionally than AIC's. Rejected
for now because it is a different prompt with a different grounding claim, and the accessibility
feature's honesty depends on being able to say exactly where the words came from
([ADR-0015](0015-accessibility-descriptions.md)). It is the obvious thing to revisit first.

## Consequences

- **Three display features degrade on a Cleveland artwork, and each has a defined fallback.**
  No `lqip`, so the crossfade starts from the previous artwork rather than from a blur. No
  `alt_text`, so the `<img>` alt falls back to the title and no AI is offered. No `color`, so
  the overlay uses its default scrim — which M8 already made strong enough to stand alone
  precisely because the AIC value turned out to be a hint rather than a measurement.
- **`ArtworkSource` finally has two implementations, and one of them is the only one.**
  `docs/architecture.md` can stop describing it as an intended seam. It is still a narrow seam:
  it describes live sources, and a third one would fit it without changes.
- **Switching source clears the filters and the history.** The two vocabularies have nothing in
  common and the two id spaces overlap, so carrying either across would show a filter that
  silently matches nothing, or offer to go back to an artwork the current source cannot serve.
- **The filter control has two states on Cleveland, not three.** Exclusion is a NOT over the
  canonical facet layer, which a live source does not have, so offering it was offering a state
  the server would reject and the panel would drop on the next redraw. `setExcludable` on the
  filter group makes the cycle off → include → off, and the hint above the groups says so.
  Found in a browser, M17; ADR-0014 carries the other half of it.
- **Cleveland's filter counts cost ten requests, once per hour per process.** There is no facet
  endpoint and deriving one would mean the walk this ADR exists to avoid. Cached in the client.
- **What would make us revisit this:** wanting Curated or "For you" across both collections,
  which is the point at which items 5 and 6 have to be paid; or wanting the AI features on
  Cleveland, which is the `description`-grounding question above.
