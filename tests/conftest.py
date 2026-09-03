import json
from pathlib import Path

import pytest

from app.core.config import Settings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "aic"


def load_fixture(name: str) -> dict:
    """Load a recorded AIC response.

    Fixtures are real captured responses, not hand-written dicts — a hand-written fixture
    encodes our assumption about the API, which is the thing contract tests exist to check.
    """
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings() -> Settings:
    return Settings(
        aic_user_agent="vitrine-tests (karolkczaj@gmail.com)",
        aic_base_url="https://api.artic.edu/api/v1",
        aic_timeout_seconds=5.0,
        aic_max_requests_per_minute=60,
    )


@pytest.fixture
def search_response() -> dict:
    return load_fixture("artwork_search_public_domain.json")


@pytest.fixture
def detail_response() -> dict:
    return load_fixture("artwork_detail_27992.json")


@pytest.fixture
def no_image_response() -> dict:
    return load_fixture("artwork_detail_no_image.json")
