"""Personal affinity: what you have liked, expressed as a preference over facets.

Deliberately the same shape as `scoring.py` — one weights dict with a comment per signal,
one pure `score`, one `explain` that prints the working. If this cannot say
"you are seeing this because you liked 7 Japanese prints", it is too clever and should be
simplified rather than tuned. See ADR-0010.

**Explicit feedback only.** Likes, dislikes and hides, nothing else. No dwell time, no
"you did not skip it", no inference from silence. A single-user local app has almost no
data to learn from, and the little it has is worth keeping legible: every number below
traces back to a key the user actually pressed.

**A dislike is not a hide.** M13 put a verdict between the two, because the original pair
had nothing in the middle: `hide` removes the artwork from selection outright, so it could
never also mean "less of this". A dislike is a ranking signal and nothing else — the
artwork stays in the rotation, and only its facets are counted against.

**Curated is untouched.** This is a third mode, not a change to the second. ADR-0006's
claim that curated ranking is reproducible and explainable survives only if curated stays
the same for everybody, and `--explain` keeps meaning what it says.

Pure: no I/O, no clock, no randomness. The profile is built from facet lists the caller
loaded, and scoring a candidate is a dictionary lookup.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

# Below this many likes there is nothing to personalise from, and a profile built on two
# artworks would mostly be reporting an accident. The mode falls back to curated ranking
# and says so, rather than showing a confident recommendation drawn from nothing.
MIN_LIKES_FOR_PROFILE: Final[int] = 5

# How much the affinity is allowed to move a candidate, as a multiplier on its curated
# score: final = curated * (1 + ALPHA * affinity). At 1.0 a perfect match doubles, which
# reorders the pool without abandoning the quality signal that got a work into it.
# The one number here that is a taste rather than a definition.
ALPHA: Final[float] = 1.0

# What a facet group is worth in the profile. Not equal, because they are not equally
# informative about a person: liking six Japanese prints says more about what you want to
# look at than that six of them were prints.
GROUP_WEIGHTS: Final[dict[str, float]] = {
    # What the picture is *of* is the closest thing here to "what you like".
    "subject": 1.25,
    # Culture and period. Nearly as telling, and the facet people describe themselves by.
    "style": 1.0,
    # The weakest of the three. Half the collection is prints; liking prints is close to
    # saying nothing, and without this the profile collapses onto whatever is commonest.
    "type": 0.5,
}
NEUTRAL_GROUP_WEIGHT: Final[float] = 1.0

# A hidden artwork's facets count against the profile, at less than a like counts for.
# Hiding is usually about one artwork rather than about a category — one bad picture at
# 3am — so it should nudge rather than veto. The veto is that hidden artworks are excluded
# outright from selection, which is a different mechanism entirely.
HIDE_PENALTY: Final[float] = 0.5

# A dislike, on the other hand, is *only* the nudge — there is no exclusion behind it, so
# the nudge is all the user gets for pressing the key and it has to be worth pressing.
# Weighted equal to a like, and opposite: "less of this" should move the ranking as far as
# "more of this" does, or the control is decorative.
DISLIKE_PENALTY: Final[float] = 1.0


def _group_of(facet: str) -> str:
    group, _, _ = facet.partition(".")
    return group


@dataclass(frozen=True)
class AffinityProfile:
    """Per-facet weights in [-1, 1], built from likes and hides.

    `likes` is carried so the display can say what the profile is made of, which is the
    difference between a recommendation and a black box.
    """

    weights: Mapping[str, float] = field(default_factory=dict)
    likes: int = 0
    hides: int = 0
    dislikes: int = 0

    @property
    def is_usable(self) -> bool:
        return self.likes >= MIN_LIKES_FOR_PROFILE and bool(self.weights)

    def top(self, limit: int = 3) -> list[tuple[str, float]]:
        """The facets carrying the profile, strongest first. What the UI says out loud."""
        positive = [(facet, w) for facet, w in self.weights.items() if w > 0]
        return sorted(positive, key=lambda pair: (-pair[1], pair[0]))[:limit]


def build_profile(
    liked_facets: Iterable[Sequence[str]],
    hidden_facets: Iterable[Sequence[str]] = (),
    disliked_facets: Iterable[Sequence[str]] = (),
) -> AffinityProfile:
    """Turn the facets of judged artworks into per-facet weights.

    Frequency, weighted by group, normalised to the strongest facet so the result is
    comparable regardless of how many artworks went into it. Normalising to the maximum
    rather than to the total is what keeps a profile built from six likes as decisive as
    one built from sixty — otherwise the whole thing quietly fades as it learns more.

    Dislikes and hides both subtract, at different strengths and for different reasons —
    see `DISLIKE_PENALTY` and `HIDE_PENALTY`.
    """
    liked = list(liked_facets)
    hidden = list(hidden_facets)
    disliked = list(disliked_facets)

    tally: dict[str, float] = defaultdict(float)
    for facets in liked:
        for facet in set(facets):
            tally[facet] += GROUP_WEIGHTS.get(_group_of(facet), NEUTRAL_GROUP_WEIGHT)
    for against, penalty in ((hidden, HIDE_PENALTY), (disliked, DISLIKE_PENALTY)):
        for artwork_facets in against:
            for facet in set(artwork_facets):
                tally[facet] -= penalty * GROUP_WEIGHTS.get(_group_of(facet), NEUTRAL_GROUP_WEIGHT)

    strongest = max((abs(value) for value in tally.values()), default=0.0)
    weights = (
        {facet: value / strongest for facet, value in tally.items() if value} if strongest else {}
    )
    return AffinityProfile(
        weights=weights, likes=len(liked), hides=len(hidden), dislikes=len(disliked)
    )


def affinity(profile: AffinityProfile, facets: Sequence[str]) -> float:
    """How well one artwork matches the profile, in roughly [-1, 1].

    The mean over the artwork's *own* facets, not the sum: otherwise a work tagged with
    fifteen subjects outranks a better match tagged with three, and the profile ends up
    measuring how thoroughly the museum catalogued something.
    """
    if not facets or not profile.weights:
        return 0.0
    matched = [profile.weights.get(facet, 0.0) for facet in set(facets)]
    return sum(matched) / len(matched)


def personal_score(curated: float | None, profile: AffinityProfile, facets: Sequence[str]) -> float:
    """Rank a candidate: its curated score, moved by how well it matches the profile.

    Curated stays the base, so "for you" is still bounded by what looks good on a screen —
    a blurry favourite subject does not beat a well-photographed one. An unscored artwork
    is treated as mid-ranked rather than as bad, the same way curated sampling treats it.
    """
    base = 0.5 if curated is None else curated
    return base * (1.0 + ALPHA * affinity(profile, facets))


@dataclass(frozen=True)
class AffinityBreakdown:
    """`--explain`, for the personal mode. Same contract as `ScoreBreakdown`."""

    curated: float
    affinity: float
    total: float
    matched: list[tuple[str, float]]

    def format(self) -> str:
        lines = [
            f"  curated{'':<18} {self.curated:>7.4f}",
            f"  affinity{'':<17} {self.affinity:>7.4f}",
            "  matched facets:",
        ]
        lines.extend(f"    {facet:<28} {weight:>7.4f}" for facet, weight in self.matched)
        lines.append(f"  {'total':<25} {self.total:>7.4f}")
        return "\n".join(lines)


def explain(
    curated: float | None, profile: AffinityProfile, facets: Sequence[str]
) -> AffinityBreakdown:
    """Why this artwork, in numbers a person can check against the ones above."""
    matched = sorted(
        ((facet, profile.weights[facet]) for facet in set(facets) if facet in profile.weights),
        key=lambda pair: (-abs(pair[1]), pair[0]),
    )
    return AffinityBreakdown(
        curated=0.5 if curated is None else curated,
        affinity=affinity(profile, facets),
        total=personal_score(curated, profile, facets),
        matched=matched,
    )
