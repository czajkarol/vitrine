# 0006. Transparent scoring, not machine learning

Status: Accepted
Date: 2026-09-02

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
