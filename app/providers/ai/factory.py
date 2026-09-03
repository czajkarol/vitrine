"""Turn configuration into a provider, or into nothing at all.

The one place that maps a configured name to a class. Everything upstream holds an
`InterpretationProvider | None` and never asks which vendor it is — `CLAUDE.md` puts
vendor names inside this package and nowhere else.

`None` is a first-class answer, not a failure: the app is fully usable with no AI
configured, and the caller's job is to say so quietly rather than to cope with an error.
"""

import logging

from app.core.config import Settings
from app.providers.ai.anthropic import AnthropicProvider
from app.providers.ai.base import InterpretationProvider
from app.providers.ai.mock import MOCK_MODEL, MockProvider
from app.providers.ai.openai import OpenAiProvider

logger = logging.getLogger(__name__)


def create_provider(settings: Settings) -> InterpretationProvider | None:
    """Build the configured provider, or return None if AI is off or unconfigured."""
    if not settings.ai_enabled or not settings.ai_provider:
        return None

    if settings.ai_provider == "mock":
        return MockProvider(model=settings.ai_model or MOCK_MODEL)

    if settings.ai_provider == "anthropic":
        if settings.anthropic_api_key is None:
            # Configured but unusable. The app is complete without AI, so this is a
            # warning and a feature that stays off — not a refusal to start.
            logger.warning("AI_PROVIDER is anthropic but ANTHROPIC_API_KEY is not set.")
            return None
        return AnthropicProvider(settings, settings.anthropic_api_key.get_secret_value())

    if settings.ai_provider == "openai":
        if settings.openai_api_key is None:
            logger.warning("AI_PROVIDER is openai but OPENAI_API_KEY is not set.")
            return None
        return OpenAiProvider(settings, settings.openai_api_key.get_secret_value())

    # Unreachable while `ai_provider` is a Literal of what exists, which is the point of
    # typing it that way: a name nobody implemented fails at startup, not at the first
    # request an hour later.
    raise ValueError(f"unsupported AI provider: {settings.ai_provider!r}")
