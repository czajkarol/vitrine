# Architecture Decision Records

Short records of decisions that were expensive to make and would be expensive to reverse.

Each one says what was decided, what the alternatives were, and what it costs us. The value is
in the "why" — anyone can read the code to find out what. These are also the clearest evidence
in the repository of human judgement directing the work, which is worth something on its own.

Write one when a decision closes off an alternative that a reasonable engineer would have picked.
Do not write one for routine choices.

Never edit an accepted ADR to change its decision. Write a new one and mark the old superseded.
A postscript that corrects a *premise*, or records what the built thing actually did, is fine and
is how several of these carry their corrections — the decision stays as it was taken.

All twelve were re-read against the code on 2026-09-04, at the end of M12. 0009's facet
counts and 0010's threshold, weights and formula still match the code exactly. 0003 gained a
third postscript: fetching an export is now an alternative to walking, which one of its costs
assumed was impossible. 0012 is the only Proposed one and is deliberately unbuilt.

The first eight were read against the code on 2026-09-03, at the end of M6. Four gained a postscript:
0002 (where a bring-your-own key actually ends up), 0003 (indexed artworks make no AIC call at
all, not the refresh the ADR describes), 0004 (a class name), 0007 (what "again at display time"
means in practice). 0001, 0005, 0006 and 0008 describe what was built.

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-local-first-single-user.md) | Local-first, single user | Accepted |
| [0003](0003-local-artwork-index.md) | Build a local artwork index | Accepted |
| [0004](0004-defer-shared-cache.md) | Defer the shared cache to an interface | Accepted |
| [0005](0005-vanilla-frontend.md) | Vanilla frontend, no build step | Accepted |
| [0006](0006-transparent-scoring.md) | Transparent scoring, not machine learning | Accepted |
| [0007](0007-public-domain-only.md) | Public-domain artworks only | Accepted |
| [0008](0008-image-delivery-fallback.md) | Serve images direct, fall back to a backend proxy | Accepted |
| [0009](0009-canonical-facets.md) | Canonical facets over AIC's raw terms | Accepted |
| [0010](0010-personalisation-from-explicit-feedback.md) | Personalisation from explicit feedback only | Accepted |
| [0011](0011-distribute-the-index-as-a-release-asset.md) | Distribute the index as a release asset, never in Git | Accepted |
| [0012](0012-additional-art-sources.md) | Additional art sources: Cleveland if ever, and what it would cost | **Proposed** |
