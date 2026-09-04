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

Three arrived with M13-M15, and one of them supersedes a record written the same day. 0012
priced a second art source at eight items and recommended against it; the owner then asked for
Cleveland without feature parity, which is a different purchase, so 0013 supersedes the decision
and keeps the research. 0014 reverses one sentence of `docs/product-spec.md` — the filter radios
— and explains why the sentence was right about the operator and wrong about the arity. 0015 is
the accessibility description, and the interesting half of it is the alternative that was not
taken.

All twelve earlier ones were re-read against the code on 2026-09-04, at the end of M12. 0009's
facet counts and 0010's threshold, weights and formula still match the code exactly. 0003 gained
a third postscript: fetching an export is now an alternative to walking, which one of its costs
assumed was impossible.

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
| [0012](0012-additional-art-sources.md) | Additional art sources: Cleveland if ever, and what it would cost | Superseded by 0013 |
| [0013](0013-cleveland-as-a-live-source.md) | Cleveland as a live source, and the seven-eighths of 0012 we did not pay | Accepted |
| [0014](0014-multi-select-filters.md) | One tri-state control per facet, and OR inside a group | Accepted |
| [0015](0015-accessibility-descriptions.md) | Accessibility descriptions grounded in the museum's alt text | Accepted |
