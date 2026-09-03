"""Getting an interpretation of one artwork: find the metadata, then ask the provider.

Orchestration only. The prompt is built in `domain/`, the call is made in `providers/ai/`,
and this decides where the artwork comes from and what happens when something is missing.

Resolution order is local cache, then shared cache, then the provider, writing back to
both — `docs/ai-system.md`. The budget guard and the circuit breaker are the next roadmap
items and land here too.
"""

import asyncio
import logging

from app.core.config import Settings
from app.domain.artwork import Artwork
from app.domain.interpretation import (
    CacheKey,
    Interpretation,
    InterpretationCache,
    Language,
)
from app.domain.prompts import PROMPT_VERSION
from app.providers.ai.base import (
    InterpretationProvider,
    InterpretationRequest,
    ProviderUnavailableError,
)
from app.providers.aic.client import AicClient, AicError
from app.repositories.artwork_index import ArtworkIndexRepository
from app.services.fallback import FallbackSet

logger = logging.getLogger(__name__)


class ArtworkNotFoundError(LookupError):
    """No tier could produce metadata for that id, so there is nothing to interpret."""


class InterpretationService:
    def __init__(
        self,
        *,
        provider: InterpretationProvider | None,
        index: ArtworkIndexRepository,
        fallback: FallbackSet,
        client: AicClient,
        settings: Settings,
        local_cache: InterpretationCache,
        shared_cache: InterpretationCache,
    ) -> None:
        self._provider = provider
        self._index = index
        self._fallback = fallback
        self._client = client
        self._settings = settings
        # Ordered: local, then shared. The chain reads them in this order and writes back
        # to both, which is the whole of `docs/ai-system.md`'s resolution rule.
        self._caches = (local_cache, shared_cache)

    @property
    def enabled(self) -> bool:
        """Whether there is a provider at all. False is an ordinary state."""
        return self._provider is not None

    @property
    def provider_name(self) -> str | None:
        return self._provider.name if self._provider else None

    @property
    def model(self) -> str | None:
        return self._provider.model if self._provider else None

    async def find_artwork(self, artwork_id: int) -> Artwork:
        """Metadata for one id, from whichever tier has it.

        Same order as the display's own tiers, and for the same reason: the local index
        answers without a network, the bundled set covers a fresh clone with no index, and
        AIC is asked last because it is the only one that can be slow or down.
        """
        if (indexed := await self._index.get(artwork_id)) is not None:
            return indexed

        if (bundled := self._fallback.get(artwork_id)) is not None:
            return bundled

        try:
            if (remote := await self._client.get(artwork_id)) is not None:
                return remote
        except AicError as exc:
            # The artwork may well exist; we just cannot reach the museum. That is not the
            # same as an unknown id, but from here it has the same outcome.
            logger.warning("AIC lookup failed for artwork %s: %s", artwork_id, exc)

        raise ArtworkNotFoundError(f"no metadata for artwork {artwork_id}")

    async def interpret(self, artwork_id: int, language: Language) -> Interpretation:
        """One interpretation, generated on demand.

        Never called on rotation — that decision lives in the frontend and is worth an
        order of magnitude in cost, because most artworks are never asked about.

        Raises `ArtworkNotFoundError` for an unknown id, and the errors in
        `providers/ai/base.py` when the provider fails. Both resolve to a quiet note on
        the display rather than to an error dialog; the museum's own facts stay on screen
        either way.
        """
        if self._provider is None:
            # The caller checks `enabled` first. Reaching here is a bug rather than a
            # configuration state, so it says so plainly.
            raise RuntimeError("interpret() called with no provider configured")

        key = CacheKey(
            artwork_id=artwork_id,
            language=language,
            provider=self._provider.name,
            model=self._provider.model,
            prompt_version=PROMPT_VERSION,
        )
        if (cached := await self._read_caches(key)) is not None:
            return cached

        artwork = await self.find_artwork(artwork_id)
        request = InterpretationRequest(
            artwork=artwork,
            language=language,
            max_output_tokens=self._settings.ai_max_output_tokens,
        )

        try:
            async with asyncio.timeout(self._settings.ai_timeout_seconds):
                result = await self._provider.interpret(request)
        except TimeoutError as exc:
            # Short by design: if the interpretation is not ready before the artwork
            # rotates away, it is no longer wanted. Reported as unavailability so the
            # circuit breaker will count it alongside the other ways a provider fails.
            raise ProviderUnavailableError(
                f"{self._provider.name} timed out after {self._settings.ai_timeout_seconds}s"
            ) from exc

        await self._write_caches(key, result.interpretation)
        return result.interpretation

    async def _read_caches(self, key: CacheKey) -> Interpretation | None:
        """Local, then shared. A cache that raises is skipped, never propagated."""
        for cache in self._caches:
            try:
                if (hit := await cache.get(key)) is not None:
                    logger.debug(
                        "Interpretation %s served from the %s cache", key.as_string(), cache.name
                    )
                    return hit
            except Exception:
                # Deliberately broad, and deliberately not re-raised. A corrupt or
                # unreachable cache must cost one provider call, not the feature.
                logger.exception("The %s interpretation cache failed on read", cache.name)
        return None

    async def _write_caches(self, key: CacheKey, value: Interpretation) -> None:
        """Write back to every tier. The text is already on its way to the screen, so a
        failure here is logged and dropped rather than surfaced."""
        for cache in self._caches:
            try:
                await cache.put(key, value)
            except Exception:
                logger.exception("The %s interpretation cache failed on write", cache.name)
