# 0016. Inferred facets for a source that has none, above a measured confidence floor

Status: Accepted
Date: 2026-09-04

Extends [ADR-0009](0009-canonical-facets.md) and reopens item 6 of
[ADR-0013](0013-cleveland-as-a-live-source.md). Supersedes the "no machine learning" half of
[ADR-0006](0006-transparent-scoring.md), which is a prohibition this needs lifted and does not
otherwise use.

## Context

**Cleveland has one filter and the Art Institute has three.** ADR-0013 dodged the facet
vocabulary deliberately — item 6, "the facet vocabulary is a hand-written map of AIC's terms",
answered with "no canonical facets, one closed list of ten artwork types in Cleveland's own
words". That was the right call for a source we were not indexing, and it leaves the panel
lopsided: style and subject, the two filters worth having, simply do not exist on half the
app's sources.

The gap cannot be closed with more metadata work, because the metadata is not there. Cleveland
does not publish anything that maps onto `style.*` or `subject.*` the way AIC's `style_titles`
and `subject_titles` do. Every facet vitrine has is derived from words a cataloguer wrote, and
for this source those words were not written.

**But the pictures are there, and so are 131,264 labelled examples.** `artwork_facets` is the
Art Institute's own cataloguing, canonicalised — real labels, written by people who work at a
museum, across 57,607 images. That is a training set for exactly one question: *given the
picture, which facets would a cataloguer have given it?*

**This is a different question from ranking, and a much better-posed one.** ADR-0006 rejected a
learned ranker partly because there was nothing to learn from; that premise expired when
ADR-0010 landed, but it was never the right objection to *this*. Tagging has abundant ground
truth, a held-out set that costs nothing to make, and an answer that can be checked one artwork
at a time by looking at it. Ranking has none of those. The prohibition still has to come off,
because it was written broadly, but this is not the thing it was written about.

**The owner has framed this as an experiment.** Recorded rather than smoothed over: what
follows describes a shape and a set of constraints, and commits nobody to building it.

## Decision

**A facet may be inferred from the image, for a source that has no cataloguer's word for it,
and only when the model clears a floor measured per facet.**

- **Train on AIC, apply to Cleveland.** Image embeddings from a pretrained vision-language
  model, computed locally; a small classifier per facet on top, fitted to `artwork_facets`.
  Nothing trained from scratch.
- **A floor per facet, not one global threshold.** `type.painting` and `subject.landscape` are
  visible in a picture. `style.chimu` and `subject.religion` are cataloguer's knowledge that no
  amount of looking recovers. The precision of each facet at each threshold is *measurable* on
  a held-out slice of AIC, so each facet gets the threshold that buys a stated precision — and
  **a facet that never reaches it is not offered for that source at all.** The vocabulary
  Cleveland gets is therefore smaller than AIC's, and which facets it contains is an outcome of
  measurement rather than a judgement call.
- **Below the floor is no facet, not a guess.** An artwork the model is unsure about carries
  nothing. It will not appear under that filter. This is the direction the error has to run:
  showing fewer results is a narrowing the user can see, whereas a confident wrong tag is a
  filter quietly lying, which is the failure the whole Explore path is written against.
- **An inferred facet is labelled as inferred, everywhere it is used.** In the panel, in the
  filter list, and on the artwork. It is stored with its confidence and its model version, and
  it is never mixed into `artwork_facets` — a table that means "the museum said so" must keep
  meaning that.

## Alternatives considered

**Leave Cleveland with one filter.** What ADR-0013 decided, and it is still defensible. It is
also the reason the source feels like a second-class citizen in the panel, and the reason two of
the three filter groups vanish when you select it.

**Hand-map Cleveland's own fields.** Its records carry `culture` and `technique`, which would
yield *something* — but that something is a third vocabulary to canonicalise, it does not reach
subject at all, and ADR-0009 exists because hand-mapping one museum's terms was already the
expensive part. It would also not generalise to a third source.

**Infer facets for AIC too, filling gaps in its cataloguing.** Tempting and rejected for now.
AIC's facets are the training labels; a model that also writes them has no ground truth left to
be checked against, and the one thing making this safe is that AIC stays the control.

**A hosted vision model.** Costs money per artwork, needs a key, and would put a *filter* behind
a provider — contradicting "the app must be fully usable with no AI provider configured".

## Consequences

**This forces the decision ADR-0013 deferred: Cleveland has to be indexed.** Filtering means
knowing the facets of the candidates *before* choosing one, so they cannot be computed lazily
for the artwork already on screen. Fetching random artworks until one matches is not an
alternative — a filter matching 5% of the collection would mean twenty fetches per picture
shown. So this reopens items 6 and 8 of ADR-0013's table, and possibly 1 and 5 with them. **That
is the real cost of this ADR, it is much larger than the model, and it is a separate decision
that has not been taken.**

**The image walk needs the owner's explicit yes, twice.** 57,607 fetches from AIC to build the
training set is roughly sixteen hours at the documented rate, and Cleveland's collection is a
second walk against a second museum's etiquette. That is squarely the "sustained automated
traffic" the working agreement reserves to the owner, and **nothing here authorises it.**

**Precision measured on AIC will flatter what happens on Cleveland.** Different photography,
different lighting, different collection. A held-out AIC slice measures the classifier, not the
transfer, and the honest way to close that gap is to look at a sample of Cleveland's predictions
by hand before offering any facet — which is a person's afternoon, not a script.

**Everything else is cheap.** Around 57 MB of embeddings at half precision beside a 67 MB index;
hours on a CPU or minutes on any GPU to encode; seconds to fit the classifiers. No VM, no
service, no per-artwork cost. Inferred facets live in their own table, so they stay out of a
published export by default (ADR-0011) — though unlike a user's likes they are derived from the
corpus and could reasonably be shipped, which is a decision for whoever builds it rather than an
assumption.

**A model now looks at the artwork, and M14 promised one does not.** No contradiction, but the
two claims sit close enough to be confused. ADR-0015's promise is about the *spoken description*
— no model sees the picture, the words come from the museum's own `alt_text`, and the display
says so on screen. That stays exactly true. This is a different feature with the opposite
property, and it has to say so just as plainly rather than inheriting the other one's reassurance.

**Curated is untouched.** The prohibition in ADR-0006 comes off because it was written broadly
and its premise expired, not because anything here needs a learned ranker. The score stays a
weighted sum of stated signals with `--explain` behind it. If a learned signal is ever added
there it is a further decision, and the constraint ADR-0006 argued for — one visible weight
among the others, tunable to zero — is the shape it would have to take.
