# 0010. Personalisation from explicit feedback only, in a mode of its own

Status: Accepted
Date: 2026-09-04

## Context

The display has two modes. Random serves anything; Curated ranks by a transparent weighted
score (ADR-0006) that is the same for everybody. Neither knows anything about the person
watching, and after an evening of rotation the obvious wish is for the display to learn
that you keep stopping to look at Japanese prints.

Two things constrain how that can be built here.

**There is almost no data.** This is a single-user local app (ADR-0002). There is no
population to learn from, no cohort, no held-out set. Whatever signal exists is a handful of
gestures by one person, and a model fitted to that is fitting noise.

**Curated's value is that it can be explained.** ADR-0006 chose transparent weights over
machine learning precisely so that `--explain` can say why artwork A outranked artwork B.
Anything that quietly folds personal history into the curated score destroys that: the
score stops being reproducible, `--explain` starts printing something that depends on who
is asking, and the honesty ADR-0006 bought is spent.

The canonical facet layer (ADR-0009) changed what is possible, though. Every indexed
artwork now carries a small set of stable, meaningful facets, so "you like Japanese prints"
is expressible as arithmetic over `style.japanese` and `type.print` rather than as an
embedding.

## Decision

**Explicit feedback only, and a third mode.**

- `L` likes the artwork on screen; `X` hides it, permanently, in every mode. Those two keys
  are the entire input. There is no dwell time, no "you did not skip it", no inference from
  silence.
- `artwork_feedback` stores one row per artwork with a small snapshot (title, artist,
  `image_id`) and **no foreign key** — see migration 009: an artwork can be on screen
  without being in the index, so a foreign key would fail on exactly the setup a new user
  has, and the snapshot is what lets a favourite outlive a rebuilt index.
- `app/domain/affinity.py` mirrors `app/domain/scoring.py` deliberately: one weights dict
  with a comment per signal, one pure scoring function, one `explain()` that prints the
  working. If it cannot say "you are seeing this because you liked 7 Japanese prints", it
  is too clever and should be simplified rather than tuned.
- **"For you" is a third mode, not a change to Curated.** It ranks by
  `curated × (1 + α · affinity)`, so curated quality still bounds it — a blurry favourite
  subject does not beat a well-photographed one — and Curated itself is untouched.
- Ranking happens in Python over a sampled pool, not in SQL. The profile changes with every
  like, lives in `domain/`, and a query carrying it could not be explained.
- **Cold start is admitted out loud.** Below five likes the mode falls back to curated
  ranking, the response says `personalised: false`, and the display says so. A
  recommendation that is not one is worse than no recommendation.

## Alternatives considered

**Implicit signals — dwell time, skips, how long an artwork was on screen before Space.**
The richest source of data here by far, and rejected. An ambient display is left running in
an empty room; "watched for nine minutes" usually means nobody was there. Inferring taste
from that is guessing, and worse, it is guessing in a way the user cannot correct, because
they never knowingly said anything.

**Fold affinity into the curated score.** Simpler: two modes instead of three, and the
"best" ranking is always personal. Rejected because it breaks ADR-0006. A curated score
that varies by viewer is not a transparent score, and `--explain` would be explaining
something the user cannot reproduce.

**Learn a model.** Even a small one — logistic regression over facets. Rejected on the same
grounds as ADR-0006 and, additionally, because at five to fifty examples it would be
elaborate arithmetic dressed as inference.

**Let hides veto a whole facet.** Hiding three Roman coins could stop showing Roman
anything. Rejected: hiding is nearly always about one artwork — one bad picture at 3am is
memorable in a way a good one is not — so a hide nudges the profile and vetoes only the
artwork itself.

## Consequences

- **The app now keeps user data it did not before.** ADR-0002 said local-first and
  single-user, which this does not violate, but `data/vitrine.db` now holds preferences
  *about* the collection as well as about the app. It is still a file the user owns and
  still never leaves the machine.
- **A liked artwork that was never indexed contributes nothing to the profile.** The facets
  come from `artwork_facets`, and an artwork we know nothing about cannot say what someone
  has a taste for. It is still listed and still shows the heart.
- **The profile is rebuilt on every request rather than cached**, deliberately: it is two
  indexed lookups against a table with tens of rows, and a cache here would be a staleness
  bug waiting for someone to like something and not see the effect.
- **α, the group weights and the five-like threshold are tastes, not truths.** Same standing
  as the curated weights (`QUESTIONS.md` #11): the tests assert ordering, never values.
- **What would make us revisit this:** if likes ever run to thousands, frequency over facets
  stops being informative and the honest move is a real model — at which point this ADR's
  reasoning about explainability has to be argued again rather than assumed.
