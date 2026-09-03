"""Application settings.

The only module in the app permitted to read the environment. Everything else takes a
`Settings` instance as an argument — see `docs/architecture.md`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# AIC's IIIF service sits behind Cloudflare and rejects requests that do not look like a
# browser, regardless of the AIC-User-Agent header. We send both: this, so the request is
# not challenged, and AIC-User-Agent, which identifies us honestly and is what actually
# lifts the block. See ADR-0008.
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Settings(BaseSettings):
    """Configuration, loaded once at startup and injected from there."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # .env.example carries AI and shared-cache keys that nothing reads until M5.
        # Ignoring extras keeps a complete .env from breaking startup.
        extra="ignore",
    )

    # --- Art Institute of Chicago ---------------------------------------------------
    aic_user_agent: str = "vitrine (karolkczaj@gmail.com)"
    aic_base_url: str = "https://api.artic.edu/api/v1"
    aic_timeout_seconds: float = 10.0
    # AIC allows 60/min per IP. The default leaves headroom for a retry burst.
    aic_max_requests_per_minute: int = Field(default=55, ge=1, le=60)

    # Sent only on IIIF image requests, never on API calls.
    image_fetch_user_agent: str = DEFAULT_BROWSER_USER_AGENT

    # --- Application -----------------------------------------------------------------
    app_env: str = "development"
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    """`text` for a human at a terminal, which is how this app is actually run. `json`
    for when the logs are being shipped somewhere that parses them."""
    database_path: str = "data/vitrine.db"
    # The languages the app actually ships strings for — frontend/locales/. Typed as a
    # Literal so a value we cannot translate fails at startup, here, rather than at every
    # page load where the only sane recovery is to discard the user's other preferences.
    default_language: Literal["en", "pl"] = "en"
    # Seconds, and one of the values on the menu — same reasoning as default_language:
    # a value the UI cannot select would be discarded on every page load.
    default_interval_seconds: Literal[30, 60, 300, 900, 1800] = 300

    # --- AI ---------------------------------------------------------------------------
    # Optional throughout. `CLAUDE.md` makes it an enhancement and never a dependency, so
    # every field here has a default that means "off".
    ai_enabled: bool = False

    ai_provider: Literal["", "mock", "anthropic", "openai"] = ""
    """Only what is actually implemented. A vendor joins this list in the commit that
    builds it — a name accepted here but unbuilt would fail at the first request instead
    of at startup."""

    ai_model: str = ""
    """Empty means the provider's own default. Part of the cache key either way."""

    ai_timeout_seconds: float = Field(default=20.0, gt=0)
    ai_max_output_tokens: int = Field(default=600, gt=0)

    ai_daily_request_limit: int = Field(default=200, ge=0)
    """A hard stop, checked before a call is made rather than reconciled after it.

    Without one, a rotation set to 30 seconds with generation on every artwork would be
    2,880 calls a day. Generation is on demand, which is the real defence — this is the
    backstop for when that assumption stops holding. Zero disables AI outright."""

    ai_circuit_breaker_threshold: int = Field(default=5, ge=0)
    """Consecutive provider failures before calls stop being attempted at all. Zero
    disables the breaker."""

    ai_circuit_breaker_cooldown_seconds: float = Field(default=300.0, ge=0)

    anthropic_api_key: SecretStr | None = None
    """A SecretStr so that printing the settings object, which happens in tracebacks and
    debuggers, cannot print the key. Reading it takes a deliberate `.get_secret_value()`."""

    openai_api_key: SecretStr | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Construct settings once. Cached so the environment is read exactly one time."""
    return Settings()
