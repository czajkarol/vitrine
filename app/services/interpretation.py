"""Getting an interpretation of one artwork: find the metadata, then ask the provider.

Orchestration only. The prompt is built in `domain/`, the call is made in `providers/ai/`,
and this decides where the artwork comes from and what happens when something is missing.

Resolution order is local cache, then shared cache, then the provider, writing back to
both — `docs/ai-system.md`. The budget guard and the circuit breaker are the next roadmap
items and land here too.
"""

import asyncio
import logging
import time

from app.core.config import Settings
from app.domain.artwork import Artwork
from app.domain.circuit_breaker import CircuitBreaker, CircuitState
from app.domain.interpretation import (
    CacheKey,
    Interpretation,
    InterpretationCache,
    Language,
)
from app.domain.metrics import CacheTally, LatencySummary, Tally
from app.domain.prompts import PROMPT_VERSION
from app.providers.ai.base import (
    AiError,
    InterpretationProvider,
    InterpretationRequest,
    ProviderUnavailableError,
)
from app.providers.aic.client import AicClient, AicError
from app.repositories.ai_usage import AiUsageRepository
from app.repositories.artwork_index import ArtworkIndexRepository
from app.services.fallback import FallbackSet

logger = logging.getLogger(__name__)


class ArtworkNotFoundError(LookupError):
    """No tier could produce metadata for that id, so there is nothing to interpret."""


class CircuitOpenError(RuntimeError):
    """The provider has failed too many times in a row, so we have stopped asking.

    Deliberately not an error from `providers/ai/`: this is our decision about a provider,
    not something the provider did on this call.
    """


class BudgetExhaustedError(RuntimeError):
    """The daily request cap is spent.

    Not a provider failure: the provider is presumably fine and we are choosing not to
    spend more today. It is kept distinct from unavailability because the display says
    something different about it, and because it must never count toward the circuit
    breaker — the provider did nothing wrong.
    """


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
        usage: AiUsageRepository,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._provider = provider
        self._index = index
        self._fallback = fallback
        self._client = client
        self._settings = settings
        # Ordered: local, then shared. The chain reads them in this order and writes back
        # to both, which is the whole of `docs/ai-system.md`'s resolution rule.
        self._caches = (local_cache, shared_cache)
        self._usage = usage
        # In memory and from process start — see `domain/metrics.py` for why that is the
        # right scope. The daily spend, which must outlive a restart, is in `ai_usage`.
        self.cache = CacheTally()
        self.calls = Tally()
        self.latency = LatencySummary()
        self._breaker = breaker or CircuitBreaker(
            threshold=settings.ai_circuit_breaker_threshold,
            cooldown_seconds=settings.ai_circuit_breaker_cooldown_seconds,
        )

    @property
    def enabled(self) -> bool:
        """Whether there is a provider at all. False is an ordinary state."""
        return self._provider is not None

    def set_provider(self, provider: InterpretationProvider | None) -> None:
        """Swap the live provider, or take it away.

        Exists for bring-your-own keys, which arrive long after startup. The breaker is
        reset with it: its failure count belongs to the provider that earned it, and a key
        the user just pasted should get a call rather than a cooling period.

        The caller owns the provider's lifetime — this does not close the outgoing one,
        because it does not know whether anyone else is holding it.
        """
        self._provider = provider
        self._breaker.reset()

    @property
    def circuit_open(self) -> bool:
        """Whether calls are currently being refused. Surfaced on /api/health."""
        return self._breaker.state is CircuitState.OPEN

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
        cached = await self._read_caches(key)
        self.cache.record(hit=cached is not None)
        if cached is not None:
            # A cache hit costs nothing, so it is not capped. The budget exists to limit
            # what we spend, not what we serve.
            return cached

        if not self._breaker.allows():
            # Cache only from here, and the lookup above has already tried it.
            raise CircuitOpenError(
                f"{self._provider.name} is failing; retrying in "
                f"{self._breaker.seconds_until_retry():.0f}s"
            )

        await self._check_budget()

        artwork = await self.find_artwork(artwork_id)
        request = InterpretationRequest(
            artwork=artwork,
            language=language,
            max_output_tokens=self._settings.ai_max_output_tokens,
        )

        started = time.monotonic()
        try:
            async with asyncio.timeout(self._settings.ai_timeout_seconds):
                result = await self._provider.interpret(request)
        except TimeoutError as exc:
            # Short by design: if the interpretation is not ready before the artwork
            # rotates away, it is no longer wanted. Counted as a provider failure, because
            # from here that is what it is.
            self._record_failure()
            # Counted, and its duration with it: a provider whose every call runs to the
            # timeout is exactly what the latency figure is for.
            self._record_call(started, error=True)
            raise ProviderUnavailableError(
                f"{self._provider.name} timed out after {self._settings.ai_timeout_seconds}s"
            ) from exc
        except AiError:
            # Unreachable, refusing, or answering with something that will not validate —
            # a provider that has started returning prose is not healthy either.
            self._record_failure()
            self._record_call(started, error=True)
            raise

        self._record_call(started)
        self._breaker.record_success()

        # Recorded after the call returns, because what is being counted is what was
        # actually spent. A request that failed cost the provider nothing to answer, and
        # the circuit breaker is what deals with a provider that keeps failing.
        await self._usage.record(self._provider.name, result.usage)
        await self._write_caches(key, result.interpretation)
        return result.interpretation

    async def _check_budget(self) -> None:
        """Refuse before spending, per `docs/ai-system.md`. Cost control is a feature."""
        assert self._provider is not None
        limit = self._settings.ai_daily_request_limit
        spent = await self._usage.requests_today(self._provider.name)
        if spent >= limit:
            raise BudgetExhaustedError(
                f"{self._provider.name} has used {spent} of {limit} requests today"
            )

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

    def _record_call(self, started: float, *, error: bool = False) -> None:
        """One provider call, however it ended, and how long it took."""
        self.calls.record(error=error)
        self.latency.record((time.monotonic() - started) * 1000)

    def _record_failure(self) -> None:
        """Count a failure, and log the transition when it is the one that opens."""
        was_open = self._breaker.state is CircuitState.OPEN
        self._breaker.record_failure()
        if not was_open and self._breaker.state is CircuitState.OPEN:
            logger.warning(
                "AI circuit opened after %d consecutive failures; not calling %s for %.0fs",
                self._breaker.consecutive_failures,
                self.provider_name,
                self._breaker.seconds_until_retry(),
            )
