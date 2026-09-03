"""The Anthropic provider, with the network intercepted.

Nothing here spends money. The one test that talks to the real API is marked `live` at the
bottom and is excluded from the default run and from CI, per `tests/CLAUDE.md`.
"""

import json
import os

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.redaction import redact
from app.domain.artwork import Artwork
from app.providers.ai.anthropic import API_URL, AnthropicProvider
from app.providers.ai.base import (
    InterpretationRequest,
    InvalidResponseError,
    ProviderUnavailableError,
)
from app.providers.ai.factory import create_provider

ARTWORK = Artwork(
    id=27992,
    title="Echizen",
    artist_title="Utagawa Hiroshige",
    is_public_domain=True,
    image_id="abc",
)

ANSWER = {
    "visual_description": "A woman kneels beside two pale baskets on a shore.",
    "interpretation": "It appears to show seaweed gathering, and may read as quiet labour.",
    "themes": ["labour", "coastline"],
    "look_closer": "The green mass is cut from a separate sheet.",
    "language": "en",
}


def _reply(text: str, input_tokens: int = 400, output_tokens: int = 120) -> httpx.Response:
    """One Messages API response, shaped the way the real one is."""
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        },
    )


@pytest.fixture
def provider(settings: Settings) -> AnthropicProvider:
    return AnthropicProvider(settings, api_key="sk-ant-secret-key-1234")


def _request(language="en") -> InterpretationRequest:
    return InterpretationRequest(artwork=ARTWORK, language=language, max_output_tokens=600)


class TestTheRequest:
    @respx.mock
    async def test_sends_the_instruction_as_system_and_the_data_as_content(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(_request())

        body = json.loads(route.calls.last.request.content)
        # The split the prompt module assumes, carried through to the wire rather than
        # collapsed into one string.
        assert "You write short interpretive notes" in body["system"]
        assert "Hiroshige" not in body["system"]
        assert json.loads(body["messages"][0]["content"])["artist"] == "Utagawa Hiroshige"

    @respx.mock
    async def test_caps_the_output_tokens(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(
            InterpretationRequest(artwork=ARTWORK, language="en", max_output_tokens=123)
        )
        # A hard cap per request. Cost control is a feature, not an afterthought.
        assert json.loads(route.calls.last.request.content)["max_tokens"] == 123

    @respx.mock
    async def test_identifies_the_api_version_and_carries_the_key(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(_request())

        headers = route.calls.last.request.headers
        assert headers["anthropic-version"]
        assert headers["x-api-key"] == "sk-ant-secret-key-1234"


class TestTheResponse:
    @respx.mock
    async def test_validates_the_answer(self, provider):
        respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        result = await provider.interpret(_request())
        assert result.interpretation.themes == ["labour", "coastline"]

    @respx.mock
    async def test_records_the_real_token_counts(self, provider):
        respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER), 400, 120))
        usage = (await provider.interpret(_request())).usage
        # Reported, not estimated — this feeds a budget that is actually enforced.
        assert usage.input_tokens == 400
        assert usage.output_tokens == 120

    @respx.mock
    async def test_joins_multiple_text_blocks(self, provider):
        half = json.dumps(ANSWER)
        respx.post(API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": half[: len(half) // 2]},
                        {"type": "text", "text": half[len(half) // 2 :]},
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )
        )
        # The field is a list. Reading only the first block would silently truncate.
        assert (await provider.interpret(_request())).interpretation.language == "en"

    @respx.mock
    async def test_prose_instead_of_json_is_an_invalid_response(self, provider):
        respx.post(API_URL).mock(return_value=_reply("Certainly! Here is my reading:"))
        with pytest.raises(InvalidResponseError):
            await provider.interpret(_request())

    @respx.mock
    async def test_an_empty_answer_is_an_invalid_response(self, provider):
        respx.post(API_URL).mock(return_value=_reply("   "))
        with pytest.raises(InvalidResponseError):
            await provider.interpret(_request())


class TestFailures:
    @respx.mock
    async def test_a_timeout_is_provider_unavailability(self, provider):
        respx.post(API_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    @respx.mock
    async def test_a_connection_failure_is_provider_unavailability(self, provider):
        respx.post(API_URL).mock(side_effect=httpx.ConnectError("no route"))
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    @respx.mock
    @pytest.mark.parametrize("status", [401, 429, 500, 529])
    async def test_an_error_status_is_provider_unavailability(self, provider, status):
        respx.post(API_URL).mock(
            return_value=httpx.Response(status, json={"error": {"message": "nope"}})
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    @respx.mock
    async def test_the_key_never_appears_in_an_error(self, provider):
        respx.post(API_URL).mock(
            return_value=httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})
        )
        with pytest.raises(ProviderUnavailableError) as caught:
            await provider.interpret(_request())

        message = str(caught.value)
        # Redacted everywhere means everywhere, errors included.
        assert "sk-ant-secret-key-1234" not in message
        assert redact("sk-ant-secret-key-1234") in message


class TestConfiguration:
    def test_a_missing_key_leaves_the_feature_off_rather_than_failing_to_start(self, settings):
        configured = settings.model_copy(
            update={"ai_enabled": True, "ai_provider": "anthropic", "anthropic_api_key": None}
        )
        # The app is complete without AI, so a half-configured provider is a warning and a
        # feature that stays off — never a refusal to boot.
        assert create_provider(configured) is None

    def test_builds_the_provider_when_a_key_is_present(self, settings):
        from pydantic import SecretStr

        configured = settings.model_copy(
            update={
                "ai_enabled": True,
                "ai_provider": "anthropic",
                "anthropic_api_key": SecretStr("sk-ant-test"),
            }
        )
        built = create_provider(configured)
        assert built is not None
        assert built.name == "anthropic"

    def test_the_settings_object_does_not_print_the_key(self, settings):
        from pydantic import SecretStr

        configured = settings.model_copy(update={"anthropic_api_key": SecretStr("sk-ant-test")})
        # Tracebacks and debuggers print settings objects. SecretStr is what keeps that
        # from being a way to leak the key.
        assert "sk-ant-test" not in repr(configured)


class TestRedaction:
    def test_shows_only_the_last_four_characters(self):
        assert redact("sk-ant-api03-abcdefgh") == "…efgh"

    def test_a_short_secret_shows_none_of_itself(self):
        # Four characters out of six is most of it.
        assert redact("abcdef") == "…"

    def test_nothing_becomes_nothing(self):
        assert redact(None) == ""
        assert redact("") == ""


@pytest.mark.live
class TestAgainstTheRealApi:
    """Run by hand with a key in .env: `uv run pytest -m live`.

    This is the test that catches the API drifting — a renamed field, a changed usage
    shape, a model id that no longer exists.
    """

    async def test_interprets_a_real_artwork(self):
        settings = Settings()
        if settings.anthropic_api_key is None:
            pytest.skip("ANTHROPIC_API_KEY is not set")

        provider = AnthropicProvider(settings, settings.anthropic_api_key.get_secret_value())
        try:
            result = await provider.interpret(_request())
        finally:
            await provider.aclose()

        assert result.interpretation.language == "en"
        assert 2 <= len(result.interpretation.themes) <= 5
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0

    async def test_answers_in_polish_when_asked(self):
        settings = Settings()
        if settings.anthropic_api_key is None:
            pytest.skip("ANTHROPIC_API_KEY is not set")

        provider = AnthropicProvider(settings, settings.anthropic_api_key.get_secret_value())
        try:
            result = await provider.interpret(_request(language="pl"))
        finally:
            await provider.aclose()

        # The language field is the model confirming it followed the instruction, and
        # parse_interpretation rejects the answer if it did not.
        assert result.interpretation.language == "pl"


def test_the_environment_is_not_carrying_a_key_into_the_default_suite():
    """A guard, not a feature test.

    If a real key is in the environment, a mistake in an intercepted test could reach the
    real API and spend money. respx makes that unlikely; this makes it visible.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("a real key is present; -m live tests will run against the real API")
