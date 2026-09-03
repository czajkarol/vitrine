"""Bring-your-own API keys: where they are stored, and what leaves the process.

Two properties matter more than the mechanics and are asserted repeatedly below: a key
never appears in an HTTP response, and a store that will not cooperate turns the feature
off rather than taking the app down.
"""

from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.circuit_breaker import CircuitBreaker
from app.main import create_app
from app.repositories.credentials import (
    CredentialStoreError,
    KeyringCredentialStore,
    SqliteCredentialStore,
    create_credential_store,
)
from app.repositories.database import Database

# Long enough to be redacted rather than masked outright, and obviously not real.
FAKE_KEY = "sk-ant-test-000000000000abcd"
OTHER_KEY = "sk-openai-test-1111111wxyz"


def fake_keyring(*, works: bool = True) -> ModuleType:
    """A stand-in for the `keyring` package, holding its passwords in a dict."""
    module = ModuleType("keyring")
    store: dict[tuple[str, str], str] = {}

    def get_password(service: str, username: str) -> str | None:
        if not works:
            raise RuntimeError("no backend available")
        return store.get((service, username))

    def set_password(service: str, username: str, password: str) -> None:
        if not works:
            raise RuntimeError("no backend available")
        store[(service, username)] = password

    def delete_password(service: str, username: str) -> None:
        if (service, username) not in store:
            raise RuntimeError("no such password")
        del store[(service, username)]

    def get_keyring() -> object:
        return object()

    module.get_password = get_password  # type: ignore[attr-defined]
    module.set_password = set_password  # type: ignore[attr-defined]
    module.delete_password = delete_password  # type: ignore[attr-defined]
    module.get_keyring = get_keyring  # type: ignore[attr-defined]
    module.store = store  # type: ignore[attr-defined]
    return module


class TestSqliteStore:
    async def test_round_trips_a_key(self, database: Database):
        store = SqliteCredentialStore(database)
        await store.set("anthropic", FAKE_KEY)
        assert await store.get("anthropic") == FAKE_KEY

    async def test_keeps_one_key_per_provider(self, database: Database):
        store = SqliteCredentialStore(database)
        await store.set("anthropic", FAKE_KEY)
        await store.set("openai", OTHER_KEY)
        assert await store.get("anthropic") == FAKE_KEY
        assert await store.get("openai") == OTHER_KEY

    async def test_replaces_rather_than_duplicating(self, database: Database):
        store = SqliteCredentialStore(database)
        await store.set("anthropic", FAKE_KEY)
        await store.set("anthropic", OTHER_KEY)
        assert await store.get("anthropic") == OTHER_KEY

    async def test_delete_leaves_nothing_behind(self, database: Database):
        store = SqliteCredentialStore(database)
        await store.set("anthropic", FAKE_KEY)
        await store.delete("anthropic")
        assert await store.get("anthropic") is None

    async def test_deleting_what_is_not_there_is_not_an_error(self, database: Database):
        await SqliteCredentialStore(database).delete("anthropic")


class TestKeyringStore:
    async def test_round_trips_a_key(self):
        store = KeyringCredentialStore(fake_keyring())
        await store.set("anthropic", FAKE_KEY)
        assert await store.get("anthropic") == FAKE_KEY

    async def test_a_refusing_backend_raises_rather_than_reporting_no_key(self):
        """The difference matters: "no key" turns the feature off silently, and a keyring
        that refused is something the user needs told about."""
        store = KeyringCredentialStore(fake_keyring(works=False))
        with pytest.raises(CredentialStoreError):
            await store.get("anthropic")
        with pytest.raises(CredentialStoreError):
            await store.set("anthropic", FAKE_KEY)

    async def test_deleting_what_is_not_there_is_not_an_error(self):
        """Most backends raise. The caller asked for the key to be gone, and it is."""
        await KeyringCredentialStore(fake_keyring()).delete("anthropic")


class TestStoreSelection:
    def test_falls_back_to_the_database_without_keyring(self, database, monkeypatch):
        monkeypatch.setattr("app.repositories.credentials._load_keyring", lambda: None)
        assert create_credential_store(database).backend == "database"

    def test_falls_back_to_the_database_when_the_keyring_does_not_work(self, database, monkeypatch):
        """An installed keyring proves nothing — on a headless machine it resolves to a
        backend whose entire behaviour is to raise."""
        monkeypatch.setattr(
            "app.repositories.credentials._load_keyring", lambda: fake_keyring(works=False)
        )
        assert create_credential_store(database).backend == "database"

    def test_prefers_the_keyring_when_it_works(self, database, monkeypatch):
        monkeypatch.setattr("app.repositories.credentials._load_keyring", fake_keyring)
        assert create_credential_store(database).backend == "keyring"


@pytest.fixture
def no_keyring(monkeypatch):
    """Force the SQLite tier, so the tests below do not touch the developer's keyring."""
    monkeypatch.setattr("app.repositories.credentials._load_keyring", lambda: None)


@pytest.fixture
def client(settings: Settings, no_keyring):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class TestKeyEndpoint:
    def test_reports_nothing_configured(self, client):
        body = client.get("/api/ai/key").json()
        assert body == {
            "enabled": False,
            "provider": None,
            "model": None,
            "source": "none",
            "key_hint": "",
            "storage": "database",
        }

    def test_saving_a_key_turns_the_feature_on(self, client):
        body = client.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY}).json()
        assert body["enabled"] is True
        assert body["provider"] == "anthropic"
        assert body["model"]
        assert body["source"] == "database"

        # And /health agrees, which is what the frontend actually reads at boot.
        assert client.get("/api/health").json()["ai"]["enabled"] is True

    def test_never_returns_the_key(self, client):
        response = client.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})
        assert FAKE_KEY not in response.text
        assert response.json()["key_hint"] == "…abcd"
        assert FAKE_KEY not in client.get("/api/ai/key").text

    def test_a_short_key_shows_none_of_itself(self, client):
        client.put("/api/ai/key", json={"provider": "openai", "api_key": "12345678"})
        assert client.get("/api/ai/key").json()["key_hint"] == "…"

    def test_removing_the_key_turns_the_feature_off_again(self, client):
        client.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})
        body = client.delete("/api/ai/key").json()
        assert body["enabled"] is False
        assert body["source"] == "none"
        assert body["key_hint"] == ""
        assert client.get("/api/health").json()["ai"]["enabled"] is False

    def test_switching_provider_replaces_the_live_one(self, client):
        client.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})
        body = client.put("/api/ai/key", json={"provider": "openai", "api_key": OTHER_KEY}).json()
        assert body["provider"] == "openai"

    def test_rejects_a_provider_that_takes_no_key(self, client):
        assert (
            client.put("/api/ai/key", json={"provider": "mock", "api_key": FAKE_KEY}).status_code
            == 422
        )

    @pytest.mark.parametrize(
        "api_key",
        [
            "abc1234",  # below the minimum length
            "has spaces in it",
            "curly-quotes-are-not-ascii-\u2019",  # a paste from a styled web page
        ],
    )
    def test_rejects_what_cannot_be_a_key(self, client, api_key):
        response = client.put("/api/ai/key", json={"provider": "anthropic", "api_key": api_key})
        assert response.status_code == 422
        # And the rejection does not echo it back. See app/api/errors.py — FastAPI's
        # own 422 body would have.
        assert api_key not in response.text

    def test_strips_the_newline_a_paste_leaves_behind(self, client):
        body = client.put(
            "/api/ai/key", json={"provider": "anthropic", "api_key": f"  {FAKE_KEY}\n"}
        ).json()
        assert body["enabled"] is True
        assert body["key_hint"] == "…abcd"


class TestRestore:
    def test_a_saved_key_survives_a_restart(self, settings: Settings, no_keyring):
        with TestClient(create_app(settings)) as first:
            first.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})

        with TestClient(create_app(settings)) as second:
            body = second.get("/api/ai/key").json()
            assert body["enabled"] is True
            assert body["provider"] == "anthropic"
            assert body["key_hint"] == "…abcd"

    def test_a_key_that_has_vanished_leaves_ai_off(self, settings: Settings, no_keyring):
        """The keyring was cleared, or the database was copied without it. AI is off, and
        the app still boots — `CLAUDE.md` makes AI an enhancement, never a dependency."""
        with TestClient(create_app(settings)) as first:
            first.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})

        database = Database(settings.database_path)
        with database.connect() as connection:
            connection.execute("DELETE FROM credentials")

        with TestClient(create_app(settings)) as second:
            assert second.get("/api/ai/key").json()["enabled"] is False
            assert second.get("/api/health").json()["status"] == "ok"

    def test_a_saved_key_outranks_the_environment(self, settings: Settings, no_keyring):
        """Both configured. The pasted key is the later and more deliberate of the two."""
        configured = settings.model_copy(update={"ai_enabled": True, "ai_provider": "mock"})
        with TestClient(create_app(configured)) as first:
            assert first.get("/api/ai/key").json()["source"] == "environment"
            first.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})

        with TestClient(create_app(configured)) as second:
            body = second.get("/api/ai/key").json()
            assert body["provider"] == "anthropic"
            assert body["source"] == "database"

    def test_removing_the_key_falls_back_to_the_environment(self, settings: Settings, no_keyring):
        configured = settings.model_copy(update={"ai_enabled": True, "ai_provider": "mock"})
        with TestClient(create_app(configured)) as client:
            client.put("/api/ai/key", json={"provider": "anthropic", "api_key": FAKE_KEY})
            body = client.delete("/api/ai/key").json()
            assert body["enabled"] is True
            assert body["provider"] == "mock"
            assert body["source"] == "environment"


class TestBreakerReset:
    def test_a_new_key_does_not_inherit_the_old_one_s_cooling_period(self):
        """A key pasted into the panel should get a call, not the punishment earned by
        whatever was configured before it."""
        breaker = CircuitBreaker(threshold=1, cooldown_seconds=300)
        breaker.record_failure()
        assert not breaker.allows()
        breaker.reset()
        assert breaker.allows()
