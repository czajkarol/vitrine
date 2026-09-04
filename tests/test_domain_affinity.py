"""The affinity profile. Pure, so these are plain function calls — the same contract as
`test_domain_scoring.py`, including the rule that tests assert ordering rather than values
so the weights can be retuned freely.
"""

from app.domain.affinity import (
    MIN_LIKES_FOR_PROFILE,
    AffinityProfile,
    affinity,
    build_profile,
    explain,
    personal_score,
)


def likes(*facet_lists):
    return build_profile(facet_lists)


class TestColdStart:
    def test_a_profile_from_too_few_likes_is_not_usable(self):
        """Below the threshold there is nothing to personalise from, and a profile built
        on two artworks is mostly reporting an accident."""
        profile = likes(["style.japanese"], ["style.japanese"])
        assert profile.likes == 2
        assert profile.is_usable is False

    def test_enough_likes_makes_it_usable(self):
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        assert profile.is_usable is True

    def test_no_likes_at_all_scores_nothing(self):
        assert affinity(AffinityProfile(), ["style.japanese"]) == 0.0


class TestBuildingTheProfile:
    def test_what_you_like_most_weighs_most(self):
        profile = likes(
            ["style.japanese"],
            ["style.japanese"],
            ["style.japanese"],
            ["style.roman"],
        )
        assert profile.weights["style.japanese"] > profile.weights["style.roman"]

    def test_the_strongest_facet_is_normalised_to_one(self):
        """So a profile built from six likes is as decisive as one built from sixty.
        Normalising to the total instead would make the whole thing fade as it learned."""
        profile = likes(["style.japanese"], ["style.japanese"])
        assert profile.weights["style.japanese"] == 1.0

    def test_a_repeated_facet_on_one_artwork_counts_once(self):
        """Otherwise the profile measures how thoroughly the museum catalogued something."""
        one = likes(["subject.portrait", "subject.portrait"])
        two = likes(["subject.portrait"])
        assert one.weights == two.weights

    def test_subject_outweighs_artwork_type(self):
        """Half the collection is prints. Liking prints is close to saying nothing, and
        without the group weights the profile collapses onto whatever is commonest."""
        profile = likes(["subject.portrait", "type.print"])
        assert profile.weights["subject.portrait"] > profile.weights["type.print"]

    def test_hiding_counts_against_a_facet(self):
        profile = build_profile(
            [["style.japanese"], ["style.roman"]], hidden_facets=[["style.roman"]]
        )
        assert profile.weights["style.roman"] < profile.weights["style.japanese"]

    def test_a_hide_nudges_rather_than_vetoes(self):
        """Hiding is usually about one artwork rather than a category. The veto is that
        hidden artworks are excluded from selection outright, which is a different thing."""
        profile = build_profile([["style.roman"], ["style.roman"]], hidden_facets=[["style.roman"]])
        assert profile.weights["style.roman"] > 0

    def test_top_names_what_the_profile_is_made_of(self):
        """ "You are seeing this because you liked 7 Japanese prints" has to be something
        the code can actually say."""
        profile = likes(["style.japanese"], ["style.japanese"], ["style.japanese"], ["style.roman"])
        assert profile.top(1) == [("style.japanese", 1.0)]


class TestScoringACandidate:
    def test_a_matching_artwork_outranks_an_equal_one_that_does_not(self):
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        match = personal_score(0.5, profile, ["style.japanese"])
        other = personal_score(0.5, profile, ["style.roman"])
        assert match > other

    def test_curated_still_bounds_it(self):
        """A blurry favourite subject does not beat a well-photographed one. "For you" is
        a re-ranking of what already looks good on a screen, not a replacement for it."""
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        weak_match = personal_score(0.05, profile, ["style.japanese"])
        strong_other = personal_score(0.95, profile, ["style.roman"])
        assert strong_other > weak_match

    def test_an_unscored_artwork_is_mid_ranked_not_bad(self):
        """The same reading curated sampling takes: unscored is unranked, not poor."""
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        assert personal_score(None, profile, []) > 0

    def test_a_thoroughly_catalogued_artwork_does_not_win_on_volume(self):
        """The mean over the artwork's own facets, not the sum. Otherwise fifteen subjects
        beat a better match with three."""
        profile = likes(*([["subject.portrait"]] * MIN_LIKES_FOR_PROFILE))
        focused = personal_score(0.5, profile, ["subject.portrait"])
        diluted = personal_score(
            0.5, profile, ["subject.portrait", *[f"subject.other{i}" for i in range(14)]]
        )
        assert focused > diluted


class TestExplain:
    def test_it_shows_the_facets_that_did_the_work(self):
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        breakdown = explain(0.5, profile, ["style.japanese", "type.print"])
        assert breakdown.matched[0][0] == "style.japanese"
        assert "style.japanese" in breakdown.format()

    def test_the_total_matches_the_score(self):
        """If these ever disagree, `--explain` is explaining something other than what
        the display did, which is worse than not explaining at all."""
        profile = likes(*([["style.japanese"]] * MIN_LIKES_FOR_PROFILE))
        facets = ["style.japanese", "subject.portrait"]
        assert explain(0.4, profile, facets).total == personal_score(0.4, profile, facets)
