"""OpenAI's Chat Completions API.

The second real provider, and the one that answers the question `docs/ai-system.md` asks:
does the abstraction hold, or did it just fit the first vendor? Its shape differs from
Anthropic's in every place that would expose a lazy interface —

- the system prompt is a *message in the array*, not a separate field;
- token counts come back as `prompt_tokens` / `completion_tokens`, not
  `input_tokens` / `output_tokens`;
- the output cap is `max_completion_tokens`, not `max_tokens`;
- and JSON is a request parameter (`response_format`) rather than only an instruction.

None of that reached `base.py`. What it did change is written in the commit: the two
providers were duplicating their HTTP setup and error mapping, which is shared
implementation rather than a shared interface, so it moved into `http.py` beside them.
"""

import logging
from typing import Any, Final

from app.core.config import Settings
from app.domain.prompts import build_prompt
from app.providers.ai.base import (
    InterpretationRequest,
    InterpretationResult,
    InvalidResponseError,
    TokenUsage,
    parse_interpretation,
)
from app.providers.ai.http import ProviderHttp

logger = logging.getLogger(__name__)

OPENAI_NAME: Final[str] = "openai"
DEFAULT_MODEL: Final[str] = "gpt-4o-mini"
API_URL: Final[str] = "https://api.openai.com/v1/chat/completions"


class OpenAiProvider:
    """Implements `InterpretationProvider` against api.openai.com."""

    def __init__(self, settings: Settings, api_key: str, model: str | None = None) -> None:
        self.name = OPENAI_NAME
        self.model = model or settings.ai_model or DEFAULT_MODEL
        self._http = ProviderHttp(
            name=self.name,
            api_key=api_key,
            timeout_seconds=settings.ai_timeout_seconds,
            headers={"authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def interpret(self, request: InterpretationRequest) -> InterpretationResult:
        prompt = build_prompt(request.artwork, request.language)
        payload = {
            "model": self.model,
            # Not `max_tokens`, which this endpoint has deprecated. A model that rejects
            # this field says so in a 400, which the live test is there to surface.
            "max_completion_tokens": request.max_output_tokens,
            # JSON as a parameter rather than only as an instruction. The prompt still
            # asks for it, because the instruction is what the other providers have and
            # the prompt is shared.
            "response_format": {"type": "json_object"},
            "messages": [
                # The one structural difference that matters: the instruction is a message
                # here, not a field. It is still never mixed with the data.
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.content},
            ],
        }

        body = await self._http.post_json(API_URL, payload)
        return InterpretationResult(
            interpretation=parse_interpretation(_text_of(body), request.language),
            usage=_usage_of(body),
        )


def _text_of(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise InvalidResponseError("openai response had no choices")

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text.strip():
        # Also what a response truncated by the token cap looks like, which is worth
        # telling apart from a network problem when reading a log.
        finish = choices[0].get("finish_reason") if isinstance(choices[0], dict) else None
        raise InvalidResponseError(f"openai returned no text (finish_reason={finish!r})")
    return text


def _usage_of(body: dict[str, Any]) -> TokenUsage:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        logger.warning("OpenAI response carried no usage; recording zero.")
        return TokenUsage()
    # Different names for the same two numbers. Mapping them here is the entire reason
    # TokenUsage is ours rather than a vendor's shape passed through.
    return TokenUsage(
        input_tokens=int(usage.get("prompt_tokens", 0)),
        output_tokens=int(usage.get("completion_tokens", 0)),
    )
