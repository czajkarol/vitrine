"""The provider interface and the mock that stands in for every vendor.

Nothing here touches a network. The real providers are exercised only under `-m live`.
"""

import json

import pytest

from app.domain.artwork import Artwork
from app.providers.ai.base import (
    InterpretationRequest,
    InvalidResponseError,
    ProviderUnavailableError,
    parse_interpretation,
)
from app.providers.ai.mock import MockProvider

ARTWORK = Artwork(id=27992, title="Echizen", is_public_domain=True, image_id="abc")

VALID_PAYLOAD = {
    "visual_description": "A woman kneels beside two baskets.",
    "interpretation": "It appears to show seaweed gathering.",
    "themes": ["labour", "coastline"],
    "look_closer": "The green mass is a separate sheet.",
    "language": "en",
}


def _request(language="en", max_output_tokens=600) -> InterpretationRequest:
    return InterpretationRequest(
        artwork=ARTWORK, language=language, max_output_tokens=max_output_tokens
    )


class TestParseInterpretation:
    def test_accepts_a_bare_json_object(self):
        got = parse_interpretation(json.dumps(VALID_PAYLOAD), "en")
        assert got.themes == ["labour", "coastline"]

    @pytest.mark.parametrize("fence", ["```json\n{body}\n```", "```\n{body}\n```"])
    def test_unwraps_a_code_fence(self, fence):
        # Models do this despite being told not to. Unwrapping is not the same as
        # accepting prose: what is inside still has to validate.
        text = fence.format(body=json.dumps(VALID_PAYLOAD))
        assert parse_interpretation(text, "en").language == "en"

    def test_rejects_prose(self):
        with pytest.raises(InvalidResponseError):
            parse_interpretation("Certainly! Here is my interpretation:", "en")

    def test_rejects_valid_json_that_is_not_an_object(self):
        with pytest.raises(InvalidResponseError):
            parse_interpretation("[1, 2, 3]", "en")

    def test_rejects_a_response_missing_a_field(self):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "look_closer"}
        with pytest.raises(InvalidResponseError):
            parse_interpretation(json.dumps(payload), "en")

    def test_rejects_an_answer_in_the_wrong_language(self):
        # The field is the model confirming it followed the instruction. Text in the wrong
        # language is worse than none: the display still has the museum's facts.
        with pytest.raises(InvalidResponseError):
            parse_interpretation(json.dumps(VALID_PAYLOAD), "pl")


class TestMockProvider:
    async def test_answers_without_a_network(self):
        result = await MockProvider().interpret(_request())
        assert "Echizen" in result.interpretation.visual_description

    async def test_is_deterministic(self):
        provider = MockProvider()
        first = await provider.interpret(_request())
        second = await provider.interpret(_request())
        # The cache is keyed on provider and model; a mock that varied would make a hit
        # and a miss indistinguishable.
        assert first.interpretation == second.interpretation

    async def test_answers_in_the_requested_language(self):
        result = await MockProvider().interpret(_request(language="pl"))
        assert result.interpretation.language == "pl"
        assert "zastępczy" in result.interpretation.interpretation

    async def test_reports_usage(self):
        # Zeros here would leave ai_usage empty and the daily budget unenforceable.
        usage = (await MockProvider().interpret(_request())).usage
        assert usage.input_tokens > 0 and usage.output_tokens > 0

    async def test_counts_the_calls_that_reached_it(self):
        provider = MockProvider()
        await provider.interpret(_request())
        await provider.interpret(_request())
        assert provider.calls == 2

    async def test_can_be_made_to_fail(self):
        provider = MockProvider(fail_with=ProviderUnavailableError("down"))
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    async def test_an_untitled_work_still_validates(self):
        # AIC genuinely returns null titles. A template interpolating one straight in
        # would produce a description the model then rejects as empty.
        untitled = Artwork(id=1, title=None, is_public_domain=True, image_id="abc")
        result = await MockProvider().interpret(
            InterpretationRequest(artwork=untitled, language="en", max_output_tokens=600)
        )
        assert result.interpretation.visual_description.strip()
