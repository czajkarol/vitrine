"""Where a bring-your-own API key is kept.

Two backends, and the choice between them is made once at startup rather than per call:
the OS keyring when there is a working one, and the local SQLite file when there is not.
`docs/ai-system.md` states the preference and the condition on the fallback — storing a
key unencrypted is acceptable for a local-first app (ADR-0002) *only* if the UI says so,
which is why `backend` is part of this interface and travels all the way to the panel.

Nothing here logs a key, and nothing here returns one to a caller that is not about to
send it to the provider it belongs to. `core/redaction.redact()` is what goes in a log
line or a response.
"""

import asyncio
import logging
from importlib import import_module
from types import ModuleType
from typing import Final, Literal, Protocol

from app.repositories.database import Database

logger = logging.getLogger(__name__)

Backend = Literal["keyring", "database"]

SERVICE_NAME: Final[str] = "vitrine"
"""What the key is filed under in the OS keyring. The username is the provider name, so
one machine can hold a key for each vendor without them colliding."""

_PROBE_USERNAME: Final[str] = "__probe__"
"""A name nothing is ever stored under. Reading it is how we find out whether the keyring
actually works before trusting it with a key — an installed `keyring` with no usable
backend raises only when you use it."""


class CredentialStoreError(RuntimeError):
    """The store could not be read or written.

    Distinct from "there is no key": the caller shows the user something different for a
    keyring that refused than for a key that was never saved.
    """


class CredentialStore(Protocol):
    """One place to keep provider keys. Async because both backends block."""

    backend: Backend

    async def get(self, provider: str) -> str | None: ...

    async def set(self, provider: str, api_key: str) -> None: ...

    async def delete(self, provider: str) -> None: ...


class KeyringCredentialStore:
    """The preferred backend: the credential store the operating system already has."""

    def __init__(self, module: ModuleType) -> None:
        self.backend: Backend = "keyring"
        self._keyring = module

    async def get(self, provider: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, provider)

    def _get_sync(self, provider: str) -> str | None:
        try:
            value = self._keyring.get_password(SERVICE_NAME, provider)
        except Exception as exc:
            # A keyring backend raises whatever the platform's credential store raises,
            # which is not a type we can name here. It is logged and converted, never
            # swallowed: the caller has to be able to tell the user the key is unreadable.
            logger.warning("Reading the %s key from the keyring failed: %s", provider, exc)
            raise CredentialStoreError(f"the keyring refused to read {provider}") from exc
        return str(value) if value else None

    async def set(self, provider: str, api_key: str) -> None:
        await asyncio.to_thread(self._set_sync, provider, api_key)

    def _set_sync(self, provider: str, api_key: str) -> None:
        try:
            self._keyring.set_password(SERVICE_NAME, provider, api_key)
        except Exception as exc:
            logger.warning("Writing the %s key to the keyring failed: %s", provider, exc)
            raise CredentialStoreError(f"the keyring refused to store {provider}") from exc

    async def delete(self, provider: str) -> None:
        await asyncio.to_thread(self._delete_sync, provider)

    def _delete_sync(self, provider: str) -> None:
        try:
            self._keyring.delete_password(SERVICE_NAME, provider)
        except Exception as exc:
            # Deleting something that is not there raises on most backends. The caller
            # asked for the key to be gone, and it is.
            logger.debug("Deleting the %s key from the keyring: %s", provider, exc)


class SqliteCredentialStore:
    """The fallback: the app's own database file, unencrypted and admitted to be so."""

    def __init__(self, database: Database) -> None:
        self.backend: Backend = "database"
        self._db = database

    async def get(self, provider: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, provider)

    def _get_sync(self, provider: str) -> str | None:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT api_key FROM credentials WHERE provider = ?", (provider,)
            ).fetchone()
        return str(row["api_key"]) if row else None

    async def set(self, provider: str, api_key: str) -> None:
        await asyncio.to_thread(self._set_sync, provider, api_key)

    def _set_sync(self, provider: str, api_key: str) -> None:
        with self._db.connect() as connection:
            connection.execute(
                "INSERT INTO credentials (provider, api_key) VALUES (?, ?) "
                "ON CONFLICT(provider) DO UPDATE SET "
                "api_key = excluded.api_key, updated_at = CURRENT_TIMESTAMP",
                (provider, api_key),
            )

    async def delete(self, provider: str) -> None:
        await asyncio.to_thread(self._delete_sync, provider)

    def _delete_sync(self, provider: str) -> None:
        with self._db.connect() as connection:
            connection.execute("DELETE FROM credentials WHERE provider = ?", (provider,))


def create_credential_store(database: Database) -> CredentialStore:
    """The keyring if it is installed and works, otherwise the database.

    Decided once, at startup, so the answer cannot change between writing a key and
    reading it back — a key written to the keyring and then looked for in SQLite would
    read as "no key" and quietly turn the feature off.
    """
    module = _load_keyring()
    if module is None:
        logger.info(
            "The keyring package is not installed; a saved API key would go in the "
            "database, unencrypted. Install the 'keyring' extra to use the OS keyring."
        )
        return SqliteCredentialStore(database)
    if not _usable(module):
        logger.warning(
            "keyring is installed but has no working backend here; a saved API key "
            "would go in the database, unencrypted."
        )
        return SqliteCredentialStore(database)
    return KeyringCredentialStore(module)


def _load_keyring() -> ModuleType | None:
    """`keyring` is an optional extra. Its absence is an ordinary configuration."""
    try:
        return import_module("keyring")
    except ImportError:
        return None


def _usable(module: ModuleType) -> bool:
    """Whether this keyring can actually hold anything.

    `import keyring` succeeding proves nothing: on a headless box it resolves to a
    backend whose whole behaviour is to raise. Probing is the only honest test, and it
    costs one read of a name nothing is stored under.
    """
    try:
        if type(module.get_keyring()).__module__.startswith("keyring.backends.fail"):
            return False
        module.get_password(SERVICE_NAME, _PROBE_USERNAME)
    except Exception as exc:
        logger.debug("The keyring backend is not usable: %s", exc)
        return False
    return True
