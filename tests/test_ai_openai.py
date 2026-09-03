"""The OpenAI provider, with the network intercepted.

These tests exist as much to check the *abstraction* as the provider. Where they mirror
`test_ai_anthropic.py` almost line for line, that is the point being made: two vendors with
different request shapes, different token-count field names and different ways of asking
for JSON, behind one interface that neither of them had to change.
"""

import json

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.redaction import redact
from app.domain.artwork import Artwork
from app.providers.ai.base import (
    InterpretationRequest,
    InvalidResponseError,
    ProviderUnavailableError,
)
from app.providers.ai.factory import create_provider
from app.providers.ai.openai import API_URL, OpenAiProvider

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


def _reply(text: str, prompt_tokens: int = 400, completion_tokens: int = 120) -> httpx.Response:
    """One Chat Completions response, shaped the way the real one is."""
    return httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        },
    )


@pytest.fixture
def provider(settings: Settings) -> OpenAiProvider:
    return OpenAiProvider(settings, api_key="sk-openai-secret-key-1234")


def _request(language="en") -> InterpretationRequest:
    return InterpretationRequest(artwork=ARTWORK, language=language, max_output_tokens=600)


class TestTheRequest:
    @respx.mock
    async def test_sends_the_instruction_as_a_system_message(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(_request())

        messages = json.loads(route.calls.last.request.content)["messages"]
        # The structural difference from Anthropic: the instruction is a message here, not
        # a field. It is still never mixed with the data.
        assert messages[0]["role"] == "system"
        assert "Hiroshige" not in messages[0]["content"]
        assert json.loads(messages[1]["content"])["artist"] == "Utagawa Hiroshige"

    @respx.mock
    async def test_asks_for_json_as_a_parameter(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(_request())
        body = json.loads(route.calls.last.request.content)
        # A guarantee rather than an instruction the model may drift from. The prompt
        # still asks too, because the prompt is shared with providers that have no such
        # parameter.
        assert body["response_format"] == {"type": "json_object"}

    @respx.mock
    async def test_caps_the_output_tokens(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(
            InterpretationRequest(artwork=ARTWORK, language="en", max_output_tokens=123)
        )
        body = json.loads(route.calls.last.request.content)
        # A different field name from Anthropic's for the same idea.
        assert body["max_completion_tokens"] == 123

    @respx.mock
    async def test_authorises_with_a_bearer_token(self, provider):
        route = respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        await provider.interpret(_request())
        assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


class TestTheResponse:
    @respx.mock
    async def test_validates_the_answer(self, provider):
        respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER)))
        result = await provider.interpret(_request())
        assert result.interpretation.themes == ["labour", "coastline"]

    @respx.mock
    async def test_maps_the_vendors_token_field_names_onto_ours(self, provider):
        respx.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER), 400, 120))
        usage = (await provider.interpret(_request())).usage
        # prompt_tokens/completion_tokens here, input_tokens/output_tokens at Anthropic.
        # Mapping them is the entire reason TokenUsage is ours and not a vendor's shape.
        assert usage.input_tokens == 400
        assert usage.output_tokens == 120

    @respx.mock
    async def test_a_truncated_answer_says_why(self, provider):
        respx.post(API_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 400, "completion_tokens": 600},
                },
            )
        )
        with pytest.raises(InvalidResponseError) as caught:
            await provider.interpret(_request())
        # Hitting the token cap looks nothing like a network problem and should not read
        # like one in a log.
        assert "length" in str(caught.value)

    @respx.mock
    async def test_a_response_with_no_choices_is_invalid(self, provider):
        respx.post(API_URL).mock(return_value=httpx.Response(200, json={"choices": []}))
        with pytest.raises(InvalidResponseError):
            await provider.interpret(_request())

    @respx.mock
    async def test_prose_instead_of_json_is_an_invalid_response(self, provider):
        respx.post(API_URL).mock(return_value=_reply("Certainly! Here is my reading:"))
        with pytest.raises(InvalidResponseError):
            await provider.interpret(_request())


class TestFailures:
    @respx.mock
    async def test_a_timeout_is_provider_unavailability(self, provider):
        respx.post(API_URL).mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    @respx.mock
    @pytest.mark.parametrize("status", [401, 429, 500])
    async def test_an_error_status_is_provider_unavailability(self, provider, status):
        respx.post(API_URL).mock(
            return_value=httpx.Response(status, json={"error": {"message": "nope"}})
        )
        with pytest.raises(ProviderUnavailableError):
            await provider.interpret(_request())

    @respx.mock
    async def test_the_key_never_appears_in_an_error(self, provider):
        respx.post(API_URL).mock(
            return_value=httpx.Response(401, json={"error": {"message": "invalid api key"}})
        )
        with pytest.raises(ProviderUnavailableError) as caught:
            await provider.interpret(_request())

        assert "sk-openai-secret-key-1234" not in str(caught.value)
        assert redact("sk-openai-secret-key-1234") in str(caught.value)

    @respx.mock
    async def test_a_non_json_body_is_an_invalid_response(self, provider):
        respx.post(API_URL).mock(return_value=httpx.Response(200, text="<html>gateway</html>"))
        # A proxy or a captive portal answering instead of the API. Not a crash.
        with pytest.raises(InvalidResponseError):
            await provider.interpret(_request())


class TestConfiguration:
    def test_a_missing_key_leaves_the_feature_off(self, settings):
        configured = settings.model_copy(
            update={"ai_enabled": True, "ai_provider": "openai", "openai_api_key": None}
        )
        assert create_provider(configured) is None

    def test_builds_the_provider_when_a_key_is_present(self, settings):
        from pydantic import SecretStr

        configured = settings.model_copy(
            update={
                "ai_enabled": True,
                "ai_provider": "openai",
                "openai_api_key": SecretStr("sk-openai-test"),
            }
        )
        built = create_provider(configured)
        assert built is not None
        assert built.name == "openai"


class TestTheAbstractionItself:
    """The point of a second provider, stated as tests rather than as a claim."""

    def test_both_providers_satisfy_the_same_protocol(self, settings):
        from app.providers.ai.anthropic import AnthropicProvider
        from app.providers.ai.base import InterpretationProvider
        from app.providers.ai.mock import MockProvider

        providers: list[InterpretationProvider] = [
            MockProvider(),
            AnthropicProvider(settings, api_key="k"),
            OpenAiProvider(settings, api_key="k"),
        ]
        # Structural typing, so this is checked by mypy rather than at runtime — but the
        # list existing at all means all three really do have `name`, `model` and
        # `interpret`.
        assert [p.name for p in providers] == ["mock", "anthropic", "openai"]

    async def test_the_service_is_indifferent_to_which_one_it_holds(self, settings, tmp_path):
        import respx as respx_module

        from app.providers.ai.anthropic import API_URL as ANTHROPIC_URL
        from app.providers.ai.anthropic import AnthropicProvider
        from app.repositories.ai_usage import AiUsageRepository
        from app.repositories.artwork_index import ArtworkIndexRepository
        from app.repositories.database import Database
        from app.repositories.interpretations import (
            NullSharedCache,
            SqliteInterpretationCache,
        )
        from app.services.fallback import FallbackSet
        from app.services.interpretation import InterpretationService

        database = Database(settings.database_path)
        database.migrate()
        index = ArtworkIndexRepository(database)
        index.upsert_many_sync([ARTWORK])

        def _service(provider):
            return InterpretationService(
                provider=provider,
                index=index,
                fallback=FallbackSet(),
                client=None,  # type: ignore[arg-type]  # never reached: the index answers
                settings=settings,
                local_cache=SqliteInterpretationCache(database),
                shared_cache=NullSharedCache(),
                usage=AiUsageRepository(database),
            )

        with respx_module.mock:
            respx_module.post(ANTHROPIC_URL).mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "content": [{"type": "text", "text": json.dumps(ANSWER)}],
                        "usage": {"input_tokens": 10, "output_tokens": 20},
                    },
                )
            )
            respx_module.post(API_URL).mock(return_value=_reply(json.dumps(ANSWER), 10, 20))

            from_anthropic = await _service(AnthropicProvider(settings, api_key="k")).interpret(
                27992, "en"
            )
            from_openai = await _service(OpenAiProvider(settings, api_key="k")).interpret(
                27992, "en"
            )

        # Same domain object out of both, cached under different keys because the provider
        # is part of the key — two vendors do not produce interchangeable text.
        assert from_anthropic == from_openai
        assert AiUsageRepository(database).requests_today_sync("anthropic") == 1
        assert AiUsageRepository(database).requests_today_sync("openai") == 1


@pytest.mark.live
class TestAgainstTheRealApi:
    """`uv run pytest -m live` with OPENAI_API_KEY in .env.

    This is also what will catch `max_completion_tokens` or the default model id being
    wrong — both are things the intercepted tests cannot tell you.
    """

    async def test_interprets_a_real_artwork(self):
        settings = Settings()
        if settings.openai_api_key is None:
            pytest.skip("OPENAI_API_KEY is not set")

        provider = OpenAiProvider(settings, settings.openai_api_key.get_secret_value())
        try:
            result = await provider.interpret(_request())
        finally:
            await provider.aclose()

        assert result.interpretation.language == "en"
        assert 2 <= len(result.interpretation.themes) <= 5
        assert result.usage.input_tokens > 0
