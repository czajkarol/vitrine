"""The one interface every AI provider implements, and the errors they may raise.

Nothing outside this package names a vendor. A provider's whole job is: take a request,
call something, return a validated `Interpretation` or raise one of the errors below.

The Protocol returns usage alongside the interpretation, which `docs/architecture.md`
originally did not. It has to: the daily budget in `docs/ai-system.md` is enforced against
`ai_usage`, and a provider that does not report tokens leaves that table empty.
"""

import json
import re
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.artwork import Artwork
from app.domain.interpretation import Interpretation, Language, VisualDescription


class AiError(Exception):
    """Base for everything this package raises."""


class ProviderUnavailableError(AiError):
    """The provider could not be reached, or refused: timeout, 5xx, rate limit, no key.

    Transient by assumption. Counts toward the circuit breaker.
    """


class InvalidResponseError(AiError):
    """The provider answered, but not with something that validates.

    Also counts toward the breaker. A provider that has started returning prose where JSON
    was asked for is not healthy, and retrying it every rotation costs money for nothing.
    """


class TokenUsage(BaseModel):
    """What one call cost, as the provider reported it.

    Zeros where a provider does not say. Better an undercount than a guess: this feeds a
    budget, and an invented number would be enforced as though it were real.
    """

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class InterpretationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    artwork: Artwork
    language: Language
    max_output_tokens: int = Field(gt=0)
    """A hard cap per request, not a suggestion. `docs/ai-system.md` treats cost control as
    a feature."""


class InterpretationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    interpretation: Interpretation
    usage: TokenUsage = TokenUsage()


class InterpretationProvider(Protocol):
    """One AI vendor. Implementations live beside this file and nowhere else."""

    name: str
    """Stable identifier, part of the cache key. Not a display name."""

    model: str
    """The model actually used, also part of the cache key — the same provider on a
    different model does not produce interchangeable text."""

    async def interpret(self, request: InterpretationRequest) -> InterpretationResult: ...


class VisualDescriptionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    description: VisualDescription
    usage: TokenUsage = TokenUsage()


@runtime_checkable
class VisualDescriptionProvider(Protocol):
    """A provider that can also write an accessibility description.

    **A capability, not a configuration flag.** The owner asked for Anthropic only to begin
    with, and the honest way to express that is a second Protocol a provider either
    satisfies or does not — rather than a `if provider == "anthropic"` somewhere above
    `providers/`, which `CLAUDE.md` forbids outright, or a method on
    `InterpretationProvider` that OpenAI would have to implement by raising.

    `runtime_checkable`, so the service can ask. That only checks for the method's presence,
    which is exactly the question being asked: adding the method to `OpenAiProvider` is what
    would make OpenAI eligible, and there is no second place to remember to change.
    """

    name: str
    model: str

    async def describe(self, request: InterpretationRequest) -> VisualDescriptionResult: ...


# Models wrap JSON in a fence often enough to be worth handling, instructions
# notwithstanding. Stripping one is not the same as accepting prose: everything inside
# still has to parse and validate.
_FENCE: Final[re.Pattern[str]] = re.compile(
    r"^\s*```(?:json)?\s*(?P<body>.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE
)


def _parse_object(text: str) -> dict[str, object]:
    """Raw provider text to a JSON object, or `InvalidResponseError`.

    Shared by every provider and by both response shapes, because "the model returned
    something unparseable" is a property of language models rather than of any one vendor
    or any one prompt.
    """
    fenced = _FENCE.match(text)
    payload = fenced.group("body") if fenced else text

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InvalidResponseError(f"provider returned unparseable JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise InvalidResponseError(f"expected a JSON object, got {type(data).__name__}")
    return data


def parse_interpretation(text: str, language: Language) -> Interpretation:
    """Turn raw provider text into a validated `Interpretation`.

    Raises `InvalidResponseError` for anything that does not survive the trip. The caller
    treats that as a cache miss, not as something the user is shown.
    """
    try:
        interpretation = Interpretation(**_parse_object(text))
    except ValidationError as exc:
        raise InvalidResponseError(f"provider response did not validate: {exc}") from exc

    if interpretation.language != language:
        # The field is the model confirming it followed the instruction. A mismatch means
        # it did not, and text in the wrong language is worse than no text at all — the
        # display has museum facts to fall back on.
        raise InvalidResponseError(
            f"asked for {language}, provider answered in {interpretation.language}"
        )
    return interpretation


def parse_visual_description(text: str, language: Language) -> VisualDescription:
    """The same, for the accessibility description.

    The language check matters more here than above. A sighted reader can see that a note
    came back in the wrong language and ignore it; the accessibility path hands its text
    to a speech synthesiser, which will read English words with a Polish voice and produce
    something nobody can follow.
    """
    try:
        description = VisualDescription(**_parse_object(text))
    except ValidationError as exc:
        raise InvalidResponseError(f"provider response did not validate: {exc}") from exc

    if description.language != language:
        raise InvalidResponseError(
            f"asked for {language}, provider answered in {description.language}"
        )
    return description
