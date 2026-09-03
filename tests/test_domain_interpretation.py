"""The validated AI shape and the cache key that identifies one.

Both are pure, so these tests need no mocks and no database.
"""

import json

import pytest
from pydantic import ValidationError

from app.domain.artwork import Artwork, Thumbnail
from app.domain.interpretation import CacheKey, Interpretation
from app.domain.prompts import PROMPT_VERSION, build_prompt

VALID = {
    "visual_description": "A woman in a red kimono kneels beside two pale baskets.",
    "interpretation": "The scene appears to show seaweed gathering, and may be read as labour "
    "rendered as something quiet.",
    "themes": ["labour", "coastline", "everyday life"],
    "look_closer": "The green mass at the right is cut from a separate sheet.",
    "language": "en",
}


def _artwork(**overrides) -> Artwork:
    fields = {
        "id": 27992,
        "title": "Echizen",
        "artist_title": "Utagawa Hiroshige",
        "date_display": "1852",
        "medium_display": "Color woodblock print",
        "is_public_domain": True,
        "image_id": "abc",
    }
    return Artwork(**{**fields, **overrides})


class TestInterpretation:
    def test_accepts_a_well_formed_response(self):
        assert Interpretation(**VALID).themes == ["labour", "coastline", "everyday life"]

    @pytest.mark.parametrize("count", [0, 1, 6])
    def test_rejects_a_theme_list_outside_two_to_five(self, count):
        # Enforced rather than trimmed: a provider drifting from its instructions should
        # show up as a cache miss we can see, not as a silently shortened list.
        with pytest.raises(ValidationError):
            Interpretation(**{**VALID, "themes": ["t"] * count})

    def test_blank_themes_do_not_count_toward_the_minimum(self):
        with pytest.raises(ValidationError):
            Interpretation(**{**VALID, "themes": ["labour", "   ", ""]})

    def test_strips_surrounding_whitespace(self):
        got = Interpretation(**{**VALID, "look_closer": "  A detail.\n"})
        assert got.look_closer == "A detail."

    @pytest.mark.parametrize("field", ["visual_description", "interpretation", "look_closer"])
    def test_rejects_an_empty_text_field(self, field):
        with pytest.raises(ValidationError):
            Interpretation(**{**VALID, field: "   "})

    def test_rejects_a_language_the_app_cannot_display(self):
        with pytest.raises(ValidationError):
            Interpretation(**{**VALID, "language": "de"})


class TestCacheKey:
    def test_carries_everything_that_changes_the_answer(self):
        key = CacheKey(
            artwork_id=27992, language="en", provider="mock", model="mock-1", prompt_version=1
        )
        assert key.as_string() == "27992|en|mock|mock-1|1"

    @pytest.mark.parametrize(
        "change",
        [
            {"artwork_id": 27993},
            {"language": "pl"},
            {"provider": "other"},
            {"model": "mock-2"},
            {"prompt_version": 2},
        ],
    )
    def test_every_component_changes_the_key(self, change):
        base = {
            "artwork_id": 27992,
            "language": "en",
            "provider": "mock",
            "model": "mock-1",
            "prompt_version": 1,
        }
        assert CacheKey(**base).as_string() != CacheKey(**{**base, **change}).as_string()

    def test_rejects_a_model_name_containing_the_separator(self):
        # Otherwise two different keys could render identically and one would serve the
        # other's text.
        with pytest.raises(ValidationError):
            CacheKey(artwork_id=1, language="en", provider="mock", model="a|b", prompt_version=1)


class TestPrompt:
    def test_metadata_never_enters_the_instruction(self):
        prompt = build_prompt(_artwork(), "en")
        # The separation is the point: data goes in the content, instructions in the
        # system text, and nothing crosses.
        assert "Hiroshige" not in prompt.system
        assert "Hiroshige" in prompt.content

    def test_the_content_is_json_and_only_json(self):
        prompt = build_prompt(_artwork(), "en")
        assert json.loads(prompt.content)["title"] == "Echizen"

    def test_absent_fields_are_left_out_rather_than_sent_as_null(self):
        content = json.loads(build_prompt(_artwork(place_of_origin=None), "en").content)
        assert "place_of_origin" not in content

    def test_alt_text_is_included_when_the_museum_wrote_one(self):
        artwork = _artwork(thumbnail=Thumbnail(alt_text="Two figures on a shore."))
        assert "Two figures on a shore." in build_prompt(artwork, "en").content

    def test_asks_for_the_requested_language_by_name_and_by_code(self):
        system = build_prompt(_artwork(), "pl").system
        assert "Polish" in system
        assert '"language" field must be exactly "pl"' in system
        assert "LANGUAGE_NAME" not in system and "LANGUAGE_CODE" not in system

    def test_non_ascii_survives_as_itself(self):
        # Escapes cost tokens and make a logged prompt unreadable.
        artwork = _artwork(artist_title="Wojciech Gerson", title="Cmentarz w górach")
        assert "górach" in build_prompt(artwork, "pl").content

    def test_the_prompt_version_is_a_real_version(self):
        assert PROMPT_VERSION >= 1
