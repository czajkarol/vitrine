# 0006. Transparent scoring, not machine learning

Status: **Superseded in part by [ADR-0016](0016-inferred-facets-for-a-source-without-any.md)**
Date: 2026-09-02

**Half of this is still the decision, and half of it is not (2026-09-04).** The weighted linear
score, the single dict of weights and `--explain` are exactly what the code does and are not in
question. The blanket rejection of machine learning, in Alternatives below, is lifted by
ADR-0016.

It is lifted on its premise rather than on its reasoning. "No labels, no feedback signal, one
user" was true the day this was written and stopped being true within two days: ADR-0010 added
explicit feedback in M11, and `is_boosted` — named a paragraph above as better than anything we
could infer — was already a label nobody was using as one.

And the prohibition turned out to be aimed at the wrong target. ADR-0016 does not want a learned
*ranker*; it wants a learned *tagger*, for a second museum that has no cataloguer's words to
build facets from. That is a question with abundant ground truth, a free held-out set and an
answer anyone can check by looking at the picture — none of which ranking has. The argument
below about a learned ranker turning the most explainable part of the system into the least is
therefore **not** reversed. It still stands, and it is why Curated is untouched.

Everything below stands as it was written.

## Context

Curated mode ranks artworks by how well they suit a large dark ambient display. There is no
labelled training data, no feedback signal, and one user, so nothing to learn from. The judgement
being encoded — big images look better, letterboxing is worse, paintings beat furniture — is
already explicit and can simply be written down.

AIC additionally exposes `is_boosted`, its own curatorial signal for the museum's essentials
selection, which is better than anything we could infer.

## Decision

A weighted linear score over signals taken from real API fields, with the weights in one dict,
one comment per weight, and an `--explain` flag that prints the breakdown for any artwork.

## Alternatives considered

**A learned ranker.** No labels, one user, and it would turn the most explainable part of the
system into the least. It would also be the kind of machine learning that exists to appear on
a CV rather than to solve a problem, which reviewers notice.

**Random selection with quality filters only.** Simpler, and loses the distinction between
Explore and Curated entirely.

## Consequences

Every ranking is explainable in one sentence, which makes it debuggable and makes the mode
honest. Tuning is manual. If real usage data ever accumulates and manual weights visibly fail,
the score function is a single pure function and can be replaced behind the same call site.
