# 0012. Additional art sources: Cleveland if ever, and what it would actually cost

Status: Superseded by [ADR-0013](0013-cleveland-as-a-live-source.md)
Date: 2026-09-04

**Superseded the same day, and the research is why.** This was written as Proposed, saying no
and pricing the no: eight things a second source costs, of which one is an API client. The owner
then asked for Cleveland with the constraint "do not aim for AIC feature parity yet", which does
not dispute the price — it buys a different thing. Most of the eight items below are consequences
of *indexing* a source rather than of having two museums, and ADR-0013 does not index Cleveland.
Three of the eight were paid, three were dodged by not indexing, and two were accepted as
narrowed or degraded features.

**Everything below stands as measured** and was re-checked against the live API before ADR-0013
was built. Read this one for the facts about Cleveland's API and for the full list of what a
*fully integrated* second source would cost — which is still the bill if anyone ever wants
Curated across both collections. Read ADR-0013 for what was actually done.

## Context

vitrine shows artworks from one source. `docs/architecture.md` names an `ArtworkSource`
boundary and only `providers/aic/` implements it, so whether that boundary is real has
never been tested — the usual state of an interface with one implementation.

The collection is finite. 132,741 records, of which 57,607 clear the public-domain and
image-quality bar. That is more than anyone will look at, so the argument for a second
source is not "more artworks". It is range: AIC's holdings lean the way AIC's holdings
lean, and 24,304 of the 57,607 indexed works are prints.

Six candidates were compared (`docs/plan-improvements.md` Phase 7). Harvard and
Smithsonian require an API key and Europeana's metadata quality varies by contributing
institution, all of which fight ADR-0002's "no accounts, runs on your machine" and, in
Europeana's case, the consistent fields Curated scoring leans on. Rijksmuseum rebuilt its
API in the 2025 data-services move and the older endpoints are being retired — a moving
target. That leaves Cleveland and the Met.

**Cleveland's API was checked directly on 2026-09-04**, because a recommendation resting on
a table someone else wrote is not a recommendation. Four requests. Two things the table got
wrong:

- **41,512 CC0 records with an image**, not the ~64k the table quoted. 64k is the whole
  collection; the usable subset is what matters and it is a third smaller.
- **There is no IIIF.** The table said "900px / 3400px / TIFF, plus IIIF". A record carries
  `images.web`, `images.print` and `images.full` — three fixed URLs — and no IIIF field at
  all. `full` is a TIFF, which browsers do not display, so there are **two** usable sizes.

What the check confirmed: no key, no rate limit published or observed, `share_license_status`
is a clean per-record `"CC0"`, deep paging works (`skip=40000` returns a record, so there is
no equivalent of AIC's 1,000-record search cap — ADR-0003), and `is_highlight` is a
curatorial signal that maps onto `is_boosted`.

And the finding that matters most, which is about fields vitrine actually uses:

**Cleveland has no `lqip`, no `alt_text`, and no `color`.** All three are load-bearing here,
and each one is a feature rather than a nicety:

| Field | What it does in vitrine |
|---|---|
| `thumbnail.lqip` | The base64 blur that the crossfade starts from, before the image has arrived (M1) |
| `thumbnail.alt_text` | AIC's human-written visual description — accessibility, *and* what grounds the AI prompt (`CLAUDE.md`) |
| `color` | The overlay scrim's strength, tuned per artwork (M8) |

## Decision

*(Superseded — see the header. ADR-0013 builds Cleveland as a live source. The reasoning below
is why it is Cleveland rather than one of the other five, and that part still holds.)*

**No second source is built. If one ever is, it is Cleveland, and it is a milestone rather
than a module.**

The recommendation stands on the licence flag and the absence of a key: `share_license_status
== "CC0"` is a per-record fact of the same kind as `is_public_domain`, which means ADR-0007's
hard filter transfers without reinterpretation. The Met is larger but its search cannot filter
to public domain — you filter per record, after fetching it — which makes indexing it a very
different shape of walk.

What a second source costs, written down so the size of it is visible:

1. **`artwork_index` needs a `source` column and a composite primary key.** Artwork id 1
   exists at both museums. That migration touches every read path, every repository method,
   `history`, `artwork_feedback` — where a favourite is keyed on `artwork_id` alone — and the
   `artwork_facets` foreign key.
2. **The IIIF base stops being one remembered value.** It lives in `preferences` today. For
   Cleveland there is no base at all, because there is no IIIF: image URLs arrive per record.
3. **`chooseWidth()` has nothing to choose from.** It picks from AIC's cached width ladder and
   clamps to the source width (gotcha 9). Cleveland offers two usable sizes, take it or leave
   it. So does the Met. ADR-0008's proxy fallback assumes a URL shape neither has.
4. **Three display features degrade rather than fail**, per the table above: no blur to
   crossfade from, no alt text for the screen reader or the AI prompt, no per-artwork scrim.
   Each needs a defined fallback, and "the artwork just looks slightly worse and nobody wrote
   it down" is the failure mode to avoid.
5. **Curated scoring is calibrated on AIC's fields.** ADR-0006's weights read
   `is_boosted`, `has_alt_text`, dimensions and department. Two of those are absent or
   different at Cleveland, so scores from the two sources would not be comparable — and
   Curated ranks them against each other.
6. **The facet vocabulary is a hand-written map of AIC's terms** (ADR-0009,
   `domain/vocabulary.py`). Cleveland's `type`, `technique` and `culture` are a different
   vocabulary that would have to be folded into the same facets, by hand, or the filters
   would silently only work on half the corpus.
7. **The attribution is a licence condition, not a label.** Every string saying "the Art
   Institute of Chicago" — including the credit the CC BY 4.0 `description` field requires —
   becomes per-artwork, in both languages.
8. **The export gains a dimension.** ADR-0011's file is "the corpus"; it would have to say
   which sources it carries, and a merge would have to handle an export holding one of them.

That is eight things, of which one is an API client.

## Alternatives considered

**Build it now, because the abstraction is nicer with two implementations.** True, and
rejected: the app has one screen and shows one artwork at a time, and 57,607 of them is more
than anyone exhausts. The refactor is real work in exchange for range nobody has asked for.

**Add Cleveland as a second *display* source without indexing it** — call it live, like the
second tier. Rejected: it dodges items 1 and 8 and none of the rest, and it makes the display
depend on a network call for some artworks and not others, which ADR-0003 exists to avoid.

> **This is what ADR-0013 does, and this paragraph was wrong about the arithmetic.** Not
> indexing dodges 5, 6 and 8 as well — scoring, the facet vocabulary and the export are all
> consequences of being *in the index*, and a source that never enters it incurs none of them.
> Item 1 is paid in one table (`artwork_feedback`, migration 010) rather than across every read
> path. The objection about a network call for some artworks and not others stands and was
> accepted: ADR-0003 is about the *default* source being local, and choosing Cleveland is an
> explicit act with a panel line saying it is fetched live.

**Accept degraded fields silently** — no blur, no alt text, no tuned scrim, and say nothing.
Rejected explicitly. The alt-text half is the sharp one: `CLAUDE.md` grounds the AI prompt in
`alt_text` precisely so the model describes the artwork rather than inventing it, and a source
without it would need a different prompt or no AI at all. That is a decision, and it would
have to be taken out loud.

**A different second source to avoid the field gaps.** None of the six has AIC's combination
of no key, a clean licence flag, an IIIF ladder, and human-written alt text. AIC is unusually
good, which is part of why this ADR says no.

## Consequences

- **`ArtworkSource` stays an interface with one implementation**, and `docs/architecture.md`
  should be read as describing an intended seam rather than a tested one. *(Reversed by
  ADR-0013: it now has two, and the seam describes live sources specifically.)*
- **The corpus keeps AIC's shape**, and everything calibrated on it — the scoring weights, the
  facet map, the width ladder, the attribution line — stays simpler than it would otherwise be.
- **The research does not go stale quietly.** The Cleveland facts above are dated and were
  measured; if this is revisited, re-measure rather than re-read, because the table this ADR
  corrects was wrong on two of five columns after about a year.
- **What would make us revisit this:** wanting range badly enough to pay for the eight items,
  or AIC changing its terms. Nothing else. *(The owner wanted range, and ADR-0013 pays about
  three of the eight by declining to index.)*
