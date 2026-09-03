"""Anthropic's Messages API.

The first real provider. Everything it does beyond the HTTP call — building the prompt,
parsing the answer, validating it, caching, counting, breaking the circuit — already
existed and was proven against `MockProvider`, which is the whole reason
`docs/ai-system.md` insists on that ordering.

Two things this API happens to fit well. The system prompt is a separate field from the
user content, which is exactly the instruction/data split `domain/prompts.py` assumes
rather than a convention layered on top of one string. And usage comes back with real
input and output token counts, so `ai_usage` records what was spent instead of an estimate.
"""

import logging
from typing import Any, Final

import httpx

from app.core.config import Settings
from app.core.redaction import redact
from app.domain.prompts import build_prompt
from app.providers.ai.base import (
    InterpretationRequest,
    InterpretationResult,
    InvalidResponseError,
    ProviderUnavailableError,
    TokenUsage,
    parse_interpretation,
)

logger = logging.getLogger(__name__)

ANTHROPIC_NAME: Final[str] = "anthropic"
DEFAULT_MODEL: Final[str] = "claude-sonnet-5"
API_URL: Final[str] = "https://api.anthropic.com/v1/messages"
API_VERSION: Final[str] = "2023-06-01"


class AnthropicProvider:
    """Implements `InterpretationProvider` against api.anthropic.com."""

    def __init__(self, settings: Settings, api_key: str, model: str | None = None) -> None:
        self.name = ANTHROPIC_NAME
        self.model = model or settings.ai_model or DEFAULT_MODEL
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=settings.ai_timeout_seconds,
            headers={
                # The key lives here and in no other structure. It is never logged, never
                # returned from an endpoint, and never part of an error message.
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def interpret(self, request: InterpretationRequest) -> InterpretationResult:
        prompt = build_prompt(request.artwork, request.language)
        payload = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": prompt.system,
            "messages": [{"role": "user", "content": prompt.content}],
        }

        try:
            response = await self._client.post(API_URL, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"anthropic timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"anthropic unreachable: {exc}") from exc

        if response.status_code >= 400:
            # Includes an invalid key, which is not transient — but it fails the same way,
            # and the circuit breaker stopping after five identical 401s is the right
            # outcome anyway. The key is named only as its last four characters.
            raise ProviderUnavailableError(
                f"anthropic returned {response.status_code} for key {redact(self._api_key)}: "
                f"{_error_message(response)}"
            )

        body = response.json()
        return InterpretationResult(
            interpretation=parse_interpretation(_text_of(body), request.language),
            usage=_usage_of(body),
        )


def _text_of(body: dict[str, Any]) -> str:
    """Join the text blocks of a Messages response.

    A well-behaved answer here is one block, but the field is a list and treating it as
    one item would silently drop the rest of a longer answer.
    """
    blocks = body.get("content")
    if not isinstance(blocks, list):
        raise InvalidResponseError("anthropic response had no content blocks")
    text = "".join(
        block.get("text", "")
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text.strip():
        raise InvalidResponseError("anthropic returned no text")
    return text


def _usage_of(body: dict[str, Any]) -> TokenUsage:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        # Better an undercount than a guess: this feeds a budget that is enforced.
        logger.warning("Anthropic response carried no usage; recording zero.")
        return TokenUsage()
    return TokenUsage(
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )


def _error_message(response: httpx.Response) -> str:
    """The provider's own explanation, if it gave one worth repeating."""
    try:
        error = response.json().get("error", {})
        return str(error.get("message", ""))[:200]
    except ValueError:
        return response.text[:200]
