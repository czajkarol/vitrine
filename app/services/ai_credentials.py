"""Which AI provider is live, and where its key came from.

Two ways a key reaches the app, and this is the seam between them. `.env` is read once at
startup by `core/config.py`; a bring-your-own key is pasted into the settings panel at any
time and has to take effect without a restart, because a user who has just typed a key and
been told to restart the server has been told the feature does not work.

The bring-your-own key wins when both exist. It is the later and more deliberate of the
two — somebody typed it into this running app — and the alternative, silently preferring a
file they may not have looked at in months, is the surprising one.

The key itself passes through here twice: on its way to the store, and on its way to the
provider that will send it. It goes nowhere else. What leaves this module for the API is
`AiKeyStatus`, whose `key_hint` is `redact()` output and never the key.
"""

import logging
from dataclasses import dataclass
from typing import Final, Literal

from app.core.config import Settings
from app.core.redaction import redact
from app.providers.ai.base import InterpretationProvider
from app.providers.ai.factory import BYO_PROVIDERS, create_byo_provider, create_provider
from app.repositories.credentials import Backend, CredentialStore, CredentialStoreError
from app.repositories.preferences import PreferencesRepository
from app.services.interpretation import InterpretationService

logger = logging.getLogger(__name__)

BYO_PROVIDER_KEY: Final[str] = "ai_byo_provider"
"""Which vendor the user chose, in `preferences`. The key itself lives in the credential
store; this only records which of them to look for. An empty value means "none"."""

KeySource = Literal["none", "environment", "keyring", "database"]


@dataclass(frozen=True)
class AiKeyStatus:
    """What the settings panel is allowed to know about the key situation."""

    enabled: bool
    """Whether a provider is live right now — the same answer /api/health gives."""

    provider: str | None
    model: str | None

    source: KeySource
    """Where the live key came from. `environment` cannot be changed from the UI, so the
    panel offers no Remove button for it."""

    key_hint: str
    """`redact()` of the live key: at most its last four characters, and empty when the key
    came from the environment or does not exist. Never the key."""

    storage: Backend
    """Where a key saved from the panel would go. Drives the warning the UI shows when the
    answer is the unencrypted database."""


class AiCredentialService:
    def __init__(
        self,
        *,
        settings: Settings,
        credentials: CredentialStore,
        preferences: PreferencesRepository,
        interpretation: InterpretationService,
        env_provider: InterpretationProvider | None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._preferences = preferences
        self._interpretation = interpretation
        # Whatever is live, so shutdown and every swap close exactly one HTTP client.
        self._live = env_provider
        self._source: KeySource = "environment" if env_provider is not None else "none"
        self._hint = ""

    async def restore(self) -> None:
        """Apply a saved bring-your-own key, if there is one. Called once, at startup.

        Every failure here leaves the environment's own provider in place and logs. A key
        that has gone missing from the keyring — cleared by the OS, or the machine's
        keyring replaced — must degrade to "AI is off", never to a failed boot.
        """
        provider_name = await self._preferences.get(BYO_PROVIDER_KEY)
        if not provider_name:
            return
        if provider_name not in BYO_PROVIDERS:
            logger.warning("Ignoring saved AI provider %r, which is not supported.", provider_name)
            return

        try:
            api_key = await self._credentials.get(provider_name)
        except CredentialStoreError:
            logger.warning(
                "The %s store would not give up the saved %s key; AI stays off.",
                self._credentials.backend,
                provider_name,
            )
            return

        if not api_key:
            logger.warning(
                "%s is the saved AI provider but no key is in the %s store; AI stays off.",
                provider_name,
                self._credentials.backend,
            )
            return

        await self._activate(provider_name, api_key, source=self._credentials.backend)
        logger.info(
            "Using the saved %s key (%s) from the %s store.",
            provider_name,
            redact(api_key),
            self._credentials.backend,
        )

    async def save(self, provider: str, api_key: str) -> AiKeyStatus:
        """Store a key, and make it the live provider.

        Not verified against the vendor: checking would cost a real call, and the first
        interpretation is a truthful enough test. A wrong key shows up there as the
        provider being unavailable, which is what it is.
        """
        if provider not in BYO_PROVIDERS:
            raise ValueError(f"no bring-your-own support for provider {provider!r}")

        await self._credentials.set(provider, api_key)
        await self._preferences.set(BYO_PROVIDER_KEY, provider)
        await self._activate(provider, api_key, source=self._credentials.backend)
        logger.info(
            "Saved the %s key (%s) to the %s store.",
            provider,
            redact(api_key),
            self._credentials.backend,
        )
        return self.status()

    async def clear(self) -> AiKeyStatus:
        """Forget the stored key and fall back to whatever `.env` configures, if anything.

        Rebuilds the environment's provider rather than keeping one aside: a provider owns
        an HTTP client, and a client held open unused for the length of the session to
        save building one here would be the wrong trade.
        """
        stored = await self._preferences.get(BYO_PROVIDER_KEY)
        if stored:
            await self._credentials.delete(stored)
        await self._preferences.set(BYO_PROVIDER_KEY, "")

        await self._close_live()
        self._live = create_provider(self._settings)
        self._source = "environment" if self._live is not None else "none"
        self._hint = ""
        self._interpretation.set_provider(self._live)
        logger.info("Removed the saved %s key.", stored or "AI")
        return self.status()

    def status(self) -> AiKeyStatus:
        return AiKeyStatus(
            enabled=self._live is not None,
            provider=self._live.name if self._live else None,
            model=self._live.model if self._live else None,
            source=self._source,
            key_hint=self._hint,
            storage=self._credentials.backend,
        )

    async def aclose(self) -> None:
        """Close whatever provider is live. Paired with the app's own lifespan."""
        await self._close_live()

    async def _activate(self, provider: str, api_key: str, *, source: KeySource) -> None:
        """Build the provider for a key and hand it to the interpretation service."""
        built = create_byo_provider(self._settings, provider, api_key)
        # The outgoing provider is closed first, while the service still points at it and
        # so cannot start a call on a client that is halfway shut. A generation in flight
        # at this exact moment loses its connection and reads as the provider being
        # unavailable — which, from the display's side, it briefly was.
        await self._close_live()
        self._live = built
        self._source = source
        self._hint = redact(api_key)
        self._interpretation.set_provider(built)

    async def _close_live(self) -> None:
        if self._live is None:
            return
        # The mock provider holds nothing to close; the real ones hold an HTTP client.
        if (closer := getattr(self._live, "aclose", None)) is not None:
            await closer()
        self._live = None
