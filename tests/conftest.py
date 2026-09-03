import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.repositories.database import Database
from app.services import fallback

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aic"


def load_fixture(name: str) -> dict:
    """Load a recorded AIC response.

    Fixtures are real captured responses, not hand-written dicts — a hand-written fixture
    encodes our assumption about the API, which is the thing contract tests exist to check.
    """
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        aic_user_agent="vitrine-tests (karolkczaj@gmail.com)",
        aic_base_url="https://api.artic.edu/api/v1",
        aic_timeout_seconds=5.0,
        aic_max_requests_per_minute=60,
        # Never the developer's real database. Without this every test that boots the app
        # reads and writes data/vitrine.db, and the index the app is meant to serve from
        # would silently decide what the tests see.
        database_path=str(tmp_path / "test.db"),
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    db = Database(settings.database_path)
    db.migrate()
    return db


@pytest.fixture
def no_fallback_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the bundled fallback at a file that does not exist.

    The bundled set is always present in a real install, so without this the last tier
    always produces an artwork and the "everything is down" paths cannot be reached.
    """
    monkeypatch.setattr(fallback, "DEFAULT_FALLBACK_PATH", tmp_path / "absent.json")


@pytest.fixture
def search_response() -> dict:
    return load_fixture("artwork_search_public_domain.json")


@pytest.fixture
def detail_response() -> dict:
    return load_fixture("artwork_detail_27992.json")


@pytest.fixture
def no_image_response() -> dict:
    return load_fixture("artwork_detail_no_image.json")


@pytest.fixture
def listing_response() -> dict:
    """A recorded `/artworks` page — the uncapped endpoint the index is built from."""
    return load_fixture("artwork_listing_page2.json")
