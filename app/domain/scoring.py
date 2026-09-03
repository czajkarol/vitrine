"""Curated-mode scoring.

Transparent weighted signals over the local index. No machine learning — the test is
whether you can say in one sentence why artwork A outranked artwork B
(`docs/product-spec.md`). Every signal comes from a real AIC field.

Pure: given an artwork and a viewport ratio, the score is deterministic. No I/O, no clock.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.artwork import Artwork
from app.domain.indexing import source_longest_side

# One dict, one comment per weight. Weights are relative; only their ratios matter, and
# the tests assert ordering rather than values so these can be retuned freely.
WEIGHTS: Final[dict[str, float]] = {
    # AIC's own curators flagged these as essentials. The single strongest signal we have,
    # because it is the only one that encodes a human judgement about the work itself.
    "is_boosted": 3.0,
    # Bigger originals survive being thrown full-bleed at a large monitor. Below the
    # display width the image server upscales and it shows.
    "resolution": 1.5,
    # Less letterboxing. An ambient display is mostly 16:9 and a tall narrow etching
    # leaves two thirds of the screen empty.
    "aspect_ratio": 1.0,
    # Title, artist, date, medium. A work we can caption properly is a better ambient
    # experience than an anonymous fragment.
    "metadata_completeness": 1.0,
    # Someone at the museum wrote a visual description of this object. It correlates with
    # curatorial attention, and it is what grounds the AI prompt in M5.
    "has_alt_text": 0.75,
    # Paintings and prints read at a glance. Furniture, coins and documents photograph as
    # objects on a background and make poor wallpaper.
    "artwork_type": 1.25,
}

# Types that display well full-bleed, and what each is worth. Everything unlisted scores
# in the middle: unknown is not the same as bad.
TYPE_AFFINITY: Final[dict[str, float]] = {
    "Painting": 1.0,
    "Drawing and Watercolor": 0.9,
    "Print": 0.85,
    "Photograph": 0.85,
    "Textile": 0.6,
    "Sculpture": 0.5,
    "Mixed Media": 0.5,
    "Architectural Drawing": 0.45,
    "Vessel": 0.3,
    "Metalwork": 0.3,
    "Furniture": 0.2,
    "Coin": 0.1,
    "Book": 0.1,
}
NEUTRAL_TYPE_AFFINITY: Final[float] = 0.5

# The resolution above which more pixels stop helping. Roughly the largest cached IIIF
# width doubled — beyond that we are not asking for the detail anyway.
RESOLUTION_CEILING: Final[int] = 3400

DEFAULT_VIEWPORT_RATIO: Final[float] = 16 / 9


@dataclass(frozen=True)
class ScoreBreakdown:
    """Why an artwork scored what it did. Printed by `build_index.py --explain`."""

    artwork_id: int
    total: float
    signals: dict[str, float]
    contributions: dict[str, float]

    def format(self) -> str:
        lines = [f"artwork {self.artwork_id}: {self.total:.4f}"]
        for name in WEIGHTS:
            raw = self.signals.get(name, 0.0)
            weighted = self.contributions.get(name, 0.0)
            lines.append(f"  {name:<22} {raw:>6.3f} x {WEIGHTS[name]:<5} = {weighted:>7.4f}")
        return "\n".join(lines)


def resolution_signal(artwork: Artwork) -> float:
    """0..1 by the longest edge of the original, flat once it is big enough."""
    longest = source_longest_side(artwork)
    if longest is None:
        # Unknown is not bad. Score it neutrally rather than pushing it to the bottom.
        return 0.5
    return min(longest / RESOLUTION_CEILING, 1.0)


def aspect_ratio_signal(artwork: Artwork, viewport_ratio: float = DEFAULT_VIEWPORT_RATIO) -> float:
    """1.0 when the work matches the screen, falling away as it needs letterboxing."""
    thumbnail = artwork.thumbnail
    if thumbnail is None or not thumbnail.width or not thumbnail.height:
        return 0.5
    ratio = thumbnail.width / thumbnail.height
    # Compared as a proportion rather than a difference, so a panorama and a tall scroll
    # that are equally far from the screen shape score the same.
    return min(ratio, viewport_ratio) / max(ratio, viewport_ratio)


def metadata_completeness_signal(artwork: Artwork) -> float:
    """The fraction of the caption fields that are actually present."""
    fields = (
        artwork.artist_title,
        artwork.date_display,
        artwork.medium_display,
        artwork.description,
    )
    return sum(1 for field in fields if field) / len(fields)


def artwork_type_signal(artwork: Artwork) -> float:
    if not artwork.artwork_type_title:
        return NEUTRAL_TYPE_AFFINITY
    return TYPE_AFFINITY.get(artwork.artwork_type_title, NEUTRAL_TYPE_AFFINITY)


def signals(artwork: Artwork, viewport_ratio: float = DEFAULT_VIEWPORT_RATIO) -> dict[str, float]:
    """Every signal, each normalised to 0..1 before weighting."""
    thumbnail = artwork.thumbnail
    return {
        "is_boosted": 1.0 if artwork.is_boosted else 0.0,
        "resolution": resolution_signal(artwork),
        "aspect_ratio": aspect_ratio_signal(artwork, viewport_ratio),
        "metadata_completeness": metadata_completeness_signal(artwork),
        "has_alt_text": 1.0 if (thumbnail and thumbnail.alt_text) else 0.0,
        "artwork_type": artwork_type_signal(artwork),
    }


def score(artwork: Artwork, viewport_ratio: float = DEFAULT_VIEWPORT_RATIO) -> float:
    """A single 0..1 number. Divided by the total weight so it stays comparable if a
    signal is added or a weight is retuned."""
    raw = signals(artwork, viewport_ratio)
    total = sum(raw[name] * weight for name, weight in WEIGHTS.items())
    return total / sum(WEIGHTS.values())


def explain(artwork: Artwork, viewport_ratio: float = DEFAULT_VIEWPORT_RATIO) -> ScoreBreakdown:
    """The same score, with its working shown."""
    raw = signals(artwork, viewport_ratio)
    contributions = {name: raw[name] * weight for name, weight in WEIGHTS.items()}
    return ScoreBreakdown(
        artwork_id=artwork.id,
        total=sum(contributions.values()) / sum(WEIGHTS.values()),
        signals=raw,
        contributions=contributions,
    )
