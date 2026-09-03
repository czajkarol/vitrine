"""The canonical facet vocabulary: our words for AIC's cataloguing.

Pure, no I/O, and the only place the editorial judgement lives. See ADR-0009.

**Why this exists.** AIC's `style_titles` and `subject_titles` are a cataloguer's
vocabulary, and they are correct as cataloguing. In a settings panel they are not usable:
`portrait` and `portraits` are separate options with 1,612 and 1,557 artworks behind them,
`architecture` appears three times including once misspelled, and the third most common
"subject" in the whole collection is `Collected by Hugh Edwards`, which is provenance.

**The rules, written down because the next person has to extend this.**

1. **Nothing is invented.** A facet only ever absorbs raw values AIC actually returns.
2. **Nothing is silently lost.** Every raw value becomes a facet — an explicit one when it
   is merged or relabelled below, and otherwise one derived from the value itself. The
   only exception is `DROPPED`, and every entry there carries a reason.
3. **Only unambiguous duplicates are merged.** `portrait`/`portraits` and `moche`/`mochica`
   are the same thing said twice. `andes` against `south american`, or the eleven Egyptian
   dynasties against `egyptian`, are editorial opinions about art — so they stay apart.
   That is the owner's ruling, and it is why this map is much shorter than the vocabulary
   it covers.
4. **Raw data is never destroyed.** `artwork_terms` and `artwork_index.artwork_type` keep
   AIC's own values forever. This layer is derived and rebuildable with `--retag`.

**On length.** Following rule 3 leaves roughly 75 style facets and 180 subject facets. That
is deliberate — the *offering* rules in `app/api/routes.py` decide how many of them a panel
shows, and the long tail stays real and selectable rather than being folded into something
it is not. Do not shorten this by inventing merges.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, get_args

FacetGroup = Literal["type", "style", "subject"]

FACET_GROUPS: Final[tuple[FacetGroup, ...]] = get_args(FacetGroup)


@dataclass(frozen=True)
class Facet:
    """One option in the panel, and everything AIC calls it.

    `key` is the stable identity: the API value, the preference value, and — with the dot
    replaced by an underscore — the i18n key. It never changes once shipped, because a
    saved preference refers to it.
    """

    key: str
    group: FacetGroup
    label_en: str
    members: frozenset[str]
    """Raw AIC values this absorbs, matched case-insensitively and whitespace-trimmed."""


def _facet(group: FacetGroup, slug: str, label: str, *members: str) -> Facet:
    return Facet(
        key=f"{group}.{slug}",
        group=group,
        label_en=label,
        members=frozenset(m.casefold() for m in members),
    )


# --- Merges and relabels -----------------------------------------------------------
#
# Only what rule 3 allows. A single-member entry is a relabel, not a merge: AIC's value
# reads like a database field ("Japanese (culture or style)") and the panel should not.

MERGES: Final[tuple[Facet, ...]] = (
    # --- Artwork type ---------------------------------------------------------------
    # AIC's type list is closed and already reads as English, so there is almost nothing
    # to do here. `Arms` and `Armor` are deliberately not merged — a sword and a
    # breastplate are not the same object, and folding them is the editorialising rule 3
    # rules out. Same for `Furniture` and `Furnishings`.
    _facet("type", "drawing", "Drawing and watercolour", "Drawing and Watercolor"),
    _facet("type", "costume", "Costume and accessories", "Costume and Accessories"),
    _facet("type", "ritual-object", "Religious or ritual object", "Religious/Ritual Object"),
    _facet(
        "type",
        "architectural-fragment",
        "Architectural fragment",
        "Architectural fragment",
        "Architectural Fragment",
    ),
    # --- Style ----------------------------------------------------------------------
    # Centuries, written two ways by two cataloguers.
    _facet("style", "c19", "19th century", "19th century", "nineteenth century"),
    _facet("style", "c18", "18th century", "18th Century"),
    _facet("style", "c17", "17th century", "17th Century"),
    _facet("style", "c16", "16th century", "16th Century", "sixteenth century"),
    _facet("style", "c15", "15th century", "15th century"),
    _facet("style", "c14", "14th century", "14th century"),
    _facet("style", "c13", "13th century", "13th century"),
    _facet("style", "c20", "20th century", "20th Century"),
    # The same noun and its adjective.
    _facet("style", "andean", "Andean", "andes", "andean"),
    # One culture, two spellings of its name — and Moche V is a phase of Moche, so it
    # cannot sensibly stay a sibling of a name that has itself been merged away.
    _facet("style", "moche", "Moche", "moche", "mochica", "mochica v"),
    _facet("style", "americas", "Arts of the Americas", "Arts of the Americas", "americas"),
    _facet("style", "africa", "Arts of Africa", "Arts of Africa", "african Art"),
    _facet(
        "style",
        "islamic",
        "Islamic",
        "Islamic (culture or style)",
        "Arts of the Islamic World",
    ),
    # Late Edo is Edo, the same way Moche V is Moche.
    _facet("style", "edo", "Edo period", "edo (japanese period)", "late edo"),
    # AIC uses both for the same material; the narrower one has no separate meaning here.
    _facet(
        "style",
        "native-american",
        "Native American",
        "native american",
        "native north american",
    ),
    # Relabels. These are the values where the parenthetical really is a note to a
    # cataloguer rather than a distinction — decided one at a time, because `_slug` no
    # longer guesses.
    _facet("style", "japanese", "Japanese", "Japanese (culture or style)"),
    _facet("style", "chinese", "Chinese", "Chinese (culture or style)"),
    _facet("style", "korean", "Korean", "Korean (culture or style)"),
    _facet("style", "roman", "Roman", "roman (ancient, style or period)"),
    _facet("style", "roman-imperial", "Roman imperial", "imperial (roman)"),
    _facet("style", "egyptian-late", "Late period (Egyptian)", "late period (egyptian)"),
    _facet("style", "egyptian-roman", "Roman period (Egyptian)", "roman period (egyptian)"),
    _facet("style", "greco-roman-egyptian", "Greco-Roman (Egyptian)", "greco-roman (egyptian)"),
    _facet("style", "coptic", "Coptic", "coptic (historically identified as)"),
    _facet("style", "indian", "Indian", "Indian (South Asian)"),
    # --- Subject --------------------------------------------------------------------
    # Singular and plural, which is most of the noise in this vocabulary.
    _facet("subject", "portrait", "Portraits", "portrait", "portraits"),
    _facet("subject", "landscape", "Landscapes", "landscape", "landscapes"),
    _facet("subject", "man", "Men", "man", "men", "Male", "portraits: male subject"),
    _facet(
        "subject",
        "woman",
        "Women",
        "woman",
        "women",
        "female",
        "portraits: female subject",
    ),
    _facet("subject", "child", "Children", "child", "children", "portraits: child subject"),
    _facet("subject", "figure", "Figures", "figure", "figures", "figures (representations)"),
    _facet("subject", "smoking", "Smoking", "smoking", "smoking (cigarettes)"),
    _facet("subject", "bird", "Birds", "bird", "birds"),
    _facet("subject", "horse", "Horses", "horse", "horses"),
    _facet("subject", "dog", "Dogs", "dog", "dogs"),
    _facet("subject", "mountain", "Mountains", "mountain", "mountains"),
    _facet("subject", "king", "Kings", "king", "kings"),
    _facet("subject", "mother", "Mothers", "mother", "mothers"),
    _facet("subject", "family", "Families", "family", "families"),
    _facet("subject", "building", "Buildings", "building", "buildings"),
    _facet("subject", "ritual", "Ritual", "ritual", "rituals"),
    _facet("subject", "coin", "Coins", "coins"),
    _facet("subject", "vessel", "Vessels", "vessels"),
    # One word, three spellings, one of them a typo in AIC's own data.
    _facet(
        "subject",
        "architecture",
        "Architecture",
        "architecture",
        "architectural",
        "architechture",
    ),
    _facet("subject", "religion", "Religion", "religion", "religious"),
    _facet("subject", "deities", "Deities", "gods (deities)", "deities"),
    _facet("subject", "geometric", "Geometric", "geometric", "geometric motif"),
    _facet("subject", "floral", "Floral", "floral", "floral motifs"),
    # AIC writes colours both ways, and only for some colours.
    _facet("subject", "blue", "Blue", "blue", "blue (color)"),
    _facet("subject", "white", "White", "white (color)"),
    _facet("subject", "red", "Red", "red (color)"),
    _facet("subject", "green", "Green", "green (color)"),
    _facet("subject", "black", "Black", "black (color)"),
    _facet("subject", "gold", "Gold", "gold (color)"),
    _facet("subject", "yellow", "Yellow", "yellow (color)"),
    _facet("subject", "pink", "Pink", "pink (color)"),
    _facet("subject", "brown", "Brown", "brown (color)"),
    _facet("subject", "purple", "Purple", "purple (color)"),
    _facet("subject", "gray", "Grey", "gray (color)"),
    _facet("subject", "tan", "Tan", "tan (color)"),
    _facet("subject", "bronze", "Bronze", "bronze (color)"),
    _facet("subject", "rose", "Rose", "rose (color)"),
    _facet("subject", "turquoise", "Turquoise", "turquoise (color)"),
    _facet("subject", "silver", "Silver", "silver", "silver (color)"),
    # And the one colour whose bare word is a different thing entirely. `orange (fruit)`
    # is left to derive its own facet, which is the whole reason parentheticals survive
    # into the slug — see `_slug`.
    _facet("subject", "orange", "Orange", "orange (color)"),
    _facet("subject", "royalty", "Royalty", "royalty", "royal", "nobility"),
    _facet(
        "subject",
        "worlds-fair",
        "World's fairs",
        "world's fairs",
        "Chicago World's Fairs",
        "Century of Progress",
    ),
    _facet(
        "subject",
        "madonna-and-child",
        "Madonna and child",
        "Virgin and child/Madonna and child",
    ),
    _facet("subject", "boy", "Boys", "boys"),
    _facet("subject", "girl", "Girls", "girl"),
    _facet("subject", "father", "Fathers", "fathers"),
    _facet("subject", "son", "Sons", "sons"),
)


# --- Dropped -----------------------------------------------------------------------
#
# Values that are not what their group says they are. Every one carries its reason: a
# vocabulary rots when things disappear from it without a note. These are dropped from the
# facet layer only — `artwork_terms` keeps them, and `--retag` can put them back.

DROPPED: Final[Mapping[FacetGroup, Mapping[str, str]]] = {
    "type": {
        "non-art": "Not a kind of object. 51 artworks whose type is 'this is not art'.",
        "Materials": "A cataloguing bucket, not an object. One artwork.",
        "Equipment": "Likewise. Four artworks, and no two of them alike.",
    },
    "style": {},
    "subject": {
        # Provenance. Who owned it before the museum did is not what the picture is of,
        # and this one is the third most common 'subject' in the entire collection.
        "Collected by Hugh Edwards": "Provenance, not subject. 1,240 artworks.",
        "lundberg collection": "Provenance, not subject. 397 artworks.",
        # Which publication a print appeared in. Real information, wrong field.
        "Contemporaine Litteraire": "A publication, not a subject.",
        "Contemporaine Littéraire": "A publication, not a subject.",
        "Gardner's Photographic Sketch Book": "A publication, not a subject.",
        "Egypte, Nubie, Palestine et Syrie": "A publication, not a subject.",
        "Sherman's Campaign 1866": "A photographic series, not a subject.",
        "Crimea 1856": "A photographic series, not a subject.",
        "Geographical Explorations and Surveys": "A survey series, not a subject.",
        "Egypt and Palestine": "A photographic series, not a subject.",
        # The medium or the department, leaking into the subject field. Filtering
        # 'subject: photography' inside a collection of photographs says nothing.
        "photography": "A medium, not a subject. Artwork type already covers it.",
        "prints and drawings": "A department, not a subject.",
        "decorative arts": "A department, not a subject.",
    },
}


# --- Derivation --------------------------------------------------------------------

_BY_MEMBER: Final[dict[tuple[str, str], Facet]] = {
    (facet.group, member): facet for facet in MERGES for member in facet.members
}

_BY_KEY: Final[dict[str, Facet]] = {facet.key: facet for facet in MERGES}

_DROPPED_FOLDED: Final[dict[FacetGroup, frozenset[str]]] = {
    group: frozenset(value.casefold() for value in values) for group, values in DROPPED.items()
}

_SLUG_CLEAN = re.compile(r"[^a-z0-9]+")
_WHITESPACE = re.compile(r"\s+")


def _ascii(text: str) -> str:
    """Fold accents so a key stays ASCII.

    Without this `chimú` loses its last letter to the character-class filter below and
    becomes the key `chim` and the label "Chim" — a culture renamed by a regular
    expression. Decomposing first turns `ú` into `u` plus a combining mark, and the mark
    is what gets dropped.
    """
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _slug(raw: str) -> str:
    """A stable key fragment for a raw value with no explicit facet.

    **Parentheticals are kept.** The first version of this stripped them, on the theory
    that `(color)` and `(culture or style)` are notes to a cataloguer. Checked against the
    live vocabulary, that is wrong more often than it is right: AIC uses the parenthetical
    to tell two senses apart. Stripping merged `orange (color)` with `orange (fruit)`, and
    — worse, because it is the kind of error nobody would ever notice on screen —
    `edo (african)`, the Edo people of Nigeria, with `edo (japanese period)`.

    So the default is to keep everything and let two values differ. Deciding that a
    parenthetical is noise is exactly the judgement rule 3 reserves for `MERGES`, where it
    is written down one value at a time.
    """
    return _SLUG_CLEAN.sub("-", _ascii(raw.casefold())).strip("-")


# Words that stay lower case inside a title. Short enough a list that a value which
# needs more than this needs a relabel instead.
_MINOR_WORDS: Final[frozenset[str]] = frozenset(
    {"a", "an", "and", "as", "at", "de", "for", "in", "of", "on", "or", "the", "to"}
)


def _derived_label(raw: str) -> str:
    """AIC's own words, cased so a list of them reads as one list.

    AIC's cataloguing is inconsistent about case — `Arts of the Americas` sits beside
    `south american` and `early intermediate period`. A value that already carries a
    capital is left exactly alone, because it has been cased deliberately; a value with no
    capital anywhere is title-cased, which changes no word and no order.

    That is the whole transformation. Rewording is inventing, and rule 1 says not to — a
    value worth rewording gets a one-line relabel in `MERGES`, where the change is visible.
    """
    text = _WHITESPACE.sub(" ", raw).strip()
    if not text:
        return raw
    if any(c.isupper() for c in text):
        return text
    words = text.split(" ")
    return " ".join(
        word if index and word in _MINOR_WORDS else word[:1].upper() + word[1:]
        for index, word in enumerate(words)
    )


def facet_for(group: FacetGroup, raw_value: str) -> Facet | None:
    """The one facet a raw AIC value belongs to, or None if it is dropped or empty."""
    value = raw_value.strip()
    if not value:
        return None
    folded = value.casefold()
    if folded in _DROPPED_FOLDED.get(group, frozenset()):
        return None
    if (explicit := _BY_MEMBER.get((group, folded))) is not None:
        return explicit
    slug = _slug(value)
    if not slug:
        return None
    return Facet(
        key=f"{group}.{slug}",
        group=group,
        label_en=_derived_label(value),
        members=frozenset({folded}),
    )


def facets_for(group: FacetGroup, raw_values: Iterable[str]) -> set[str]:
    """The facet keys for a set of raw values. Deduplicated, because merging is the point:
    an artwork tagged both `portrait` and `portraits` is tagged `subject.portrait` once."""
    keys = set()
    for raw in raw_values:
        if (facet := facet_for(group, raw)) is not None:
            keys.add(facet.key)
    return keys


def label_for(key: str) -> str:
    """The English label for a facet key.

    Explicit facets carry a written label. A derived one is reconstructed from its slug,
    which is what the key is made of — this is the fallback for a key read back out of the
    database whose raw value is not to hand, and it is why `--retag` writes labels nowhere.
    """
    if (facet := _BY_KEY.get(key)) is not None:
        return facet.label_en
    _, _, slug = key.partition(".")
    words = slug.replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else key


def translation_key(key: str) -> str:
    """`style.japanese` becomes `facet_style_japanese`, the shape `locales/` uses."""
    return f"facet_{key.replace('.', '_')}"
