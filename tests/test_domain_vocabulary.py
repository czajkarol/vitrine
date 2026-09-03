"""The canonical facet map. Pure, so these are plain function calls.

The values used here are real ones from AIC's live vocabulary, not invented examples —
same reasoning as the recorded fixtures. Several of them are the specific pairs that caught
the first version of this module out.
"""

import pytest

from app.domain.vocabulary import (
    DROPPED,
    FACET_GROUPS,
    MERGES,
    facet_for,
    facets_for,
    label_for,
    translation_key,
)


def key(group, value):
    facet = facet_for(group, value)
    return facet.key if facet else None


class TestMerging:
    def test_singular_and_plural_are_one_facet(self):
        assert key("subject", "portrait") == key("subject", "portraits") == "subject.portrait"

    def test_a_noun_and_its_adjective_are_one_facet(self):
        assert key("style", "andes") == key("style", "andean") == "style.andean"

    def test_one_culture_spelled_two_ways(self):
        assert key("style", "moche") == key("style", "mochica") == "style.moche"

    def test_aics_own_typo_lands_on_the_right_facet(self):
        assert key("subject", "architechture") == key("subject", "architecture")

    def test_matching_ignores_case_and_surrounding_space(self):
        assert key("style", "  JAPANESE (Culture or Style)  ") == "style.japanese"

    def test_a_relabel_drops_the_cataloguers_parenthetical(self):
        facet = facet_for("style", "Japanese (culture or style)")
        assert facet is not None and facet.label_en == "Japanese"


class TestWhatIsDeliberatelyNotMerged:
    """The owner's ruling: merge unambiguous duplicates, leave judgement calls apart."""

    def test_neighbouring_cultures_stay_apart(self):
        assert key("style", "andean") != key("style", "south american")

    def test_egyptian_periods_are_not_folded_into_egyptian(self):
        assert key("style", "new kingdom") != key("style", "egyptian")

    def test_arms_and_armor_are_different_objects(self):
        assert key("type", "Arms") != key("type", "Armor")


class TestParentheticals:
    """Stripping them looks like tidying and is not. Both of these merged, wrongly, in the
    first version of this module."""

    def test_a_colour_and_a_fruit_are_not_the_same_orange(self):
        assert key("subject", "orange (color)") != key("subject", "orange (fruit)")

    def test_a_nigerian_people_is_not_a_japanese_period(self):
        assert key("style", "edo (african)") != key("style", "edo (japanese period)")

    def test_but_a_colour_written_two_ways_still_merges(self):
        """Because there is a written rule for it, not because a regex guessed."""
        assert key("subject", "blue") == key("subject", "blue (color)") == "subject.blue"


class TestDerivedFacets:
    """Every value that is not merged or dropped still becomes a facet. Nothing is lost."""

    def test_an_unmapped_value_derives_its_own_facet(self):
        assert key("style", "Pictorialism") == "style.pictorialism"

    def test_accents_fold_rather_than_truncating_the_word(self):
        """`chimú` became the key `chim` and the label "Chim" — a culture renamed by a
        regular expression."""
        facet = facet_for("style", "chimú")
        assert facet is not None
        assert facet.key == "style.chimu"
        assert facet.label_en == "Chimú"

    def test_a_value_aic_cased_deliberately_is_left_alone(self):
        facet = facet_for("style", "Arts of the Americas")
        assert facet is not None and facet.label_en == "Arts of the Americas"

    def test_an_all_lowercase_value_is_title_cased(self):
        facet = facet_for("style", "early intermediate period")
        assert facet is not None and facet.label_en == "Early Intermediate Period"

    def test_empty_and_whitespace_are_not_facets(self):
        assert facet_for("subject", "") is None
        assert facet_for("subject", "   ") is None


class TestDropping:
    def test_provenance_is_not_a_subject(self):
        assert facet_for("subject", "Collected by Hugh Edwards") is None

    def test_a_medium_is_not_a_subject(self):
        assert facet_for("subject", "photography") is None

    def test_dropping_is_case_insensitive_like_everything_else(self):
        assert facet_for("subject", "COLLECTED BY HUGH EDWARDS") is None

    def test_every_dropped_value_carries_a_reason(self):
        """A vocabulary rots when things disappear from it without a note."""
        for group, values in DROPPED.items():
            assert group in FACET_GROUPS
            for value, reason in values.items():
                assert reason.strip(), f"{group}/{value} was dropped with no reason given"


class TestFacetsFor:
    def test_two_spellings_of_one_thing_yield_one_key(self):
        assert facets_for("subject", ["portrait", "portraits"]) == {"subject.portrait"}

    def test_dropped_values_simply_vanish(self):
        assert facets_for("subject", ["Collected by Hugh Edwards", "water"]) == {"subject.water"}


class TestKeysAndLabels:
    def test_a_translation_key_is_the_facet_key_with_underscores(self):
        assert translation_key("style.japanese") == "facet_style_japanese"

    def test_label_for_knows_the_written_labels(self):
        assert label_for("subject.portrait") == "Portraits"

    def test_label_for_falls_back_to_the_slug(self):
        """Last resort, for a facet whose raw values have left the index."""
        assert label_for("style.pictorialism") == "Pictorialism"

    @pytest.mark.parametrize("facet", MERGES, ids=lambda f: f.key)
    def test_every_written_facet_is_well_formed(self, facet):
        group, _, rest = facet.key.partition(".")
        assert group == facet.group
        assert rest and rest == rest.lower()
        assert facet.label_en.strip()
        assert facet.members, "a facet that absorbs nothing is a facet that does nothing"
        # Rule 1: nothing is invented. Members are matched case-folded, so they must be
        # stored that way or they can never match.
        assert all(member == member.casefold() for member in facet.members)

    def test_no_two_written_facets_claim_the_same_raw_value(self):
        seen = set()
        for facet in MERGES:
            for member in facet.members:
                assert (facet.group, member) not in seen, f"{member} is claimed twice"
                seen.add((facet.group, member))
