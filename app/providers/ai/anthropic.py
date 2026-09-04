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

from app.core.config import Settings
from app.domain.prompts import Prompt, build_prompt, build_visual_prompt
from app.providers.ai.base import (
    InterpretationRequest,
    InterpretationResult,
    InvalidResponseError,
    TokenUsage,
    VisualDescriptionResult,
    parse_interpretation,
    parse_visual_description,
)
from app.providers.ai.http import ProviderHttp

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
        self._http = ProviderHttp(
            name=self.name,
            api_key=api_key,
            timeout_seconds=settings.ai_timeout_seconds,
            # The key lives here and in no other structure. It is never logged, never
            # returned from an endpoint, and never part of an error message.
            headers={"x-api-key": api_key, "anthropic-version": API_VERSION},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def interpret(self, request: InterpretationRequest) -> InterpretationResult:
        body = await self._ask(build_prompt(request.artwork, request.language), request)
        return InterpretationResult(
            interpretation=parse_interpretation(_text_of(body), request.language),
            usage=_usage_of(body),
        )

    async def describe(self, request: InterpretationRequest) -> VisualDescriptionResult:
        """The accessibility description — `VisualDescriptionProvider`, and Anthropic only
        for now. The wire call is identical; only the prompt and the parser differ, which
        is what `base.py` splitting `_parse_object` out was for."""
        body = await self._ask(build_visual_prompt(request.artwork, request.language), request)
        return VisualDescriptionResult(
            description=parse_visual_description(_text_of(body), request.language),
            usage=_usage_of(body),
        )

    async def _ask(self, prompt: Prompt, request: InterpretationRequest) -> dict[str, Any]:
        return await self._http.post_json(
            API_URL,
            {
                "model": self.model,
                "max_tokens": request.max_output_tokens,
                "system": prompt.system,
                "messages": [{"role": "user", "content": prompt.content}],
            },
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
