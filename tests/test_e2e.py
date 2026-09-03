"""The five Playwright flows from `docs/testing.md`, and no more.

Playwright is slow and flaky in proportion to how much you ask of it, so this file asks for
five things: that the app loads a picture, that Space changes it, that `I` opens the
overlay, that the language switches, and that with no AI configured the overlay shows the
museum's own facts and no error. Everything else lives in a unit or integration test.

These are `-m e2e`, excluded from the default run and from CI. They need Chromium:

    uv sync --all-extras
    uv run playwright install chromium
    uv run pytest -m e2e

The server is started by the fixture below rather than by the person running the tests —
against a temporary database seeded from the bundled fallback set, so no AIC API call is
needed to put something on screen. The *images* still come from artic.edu, because the
bundled set is metadata only (`app/services/fallback.py`); that is the one thing here that
touches the network, and it is what flow 1 is actually testing.
"""

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytest.importorskip("playwright", reason="the e2e extra is not installed")

# Imported after the skip above, so a machine without the e2e extra skips rather than
# fails at collection.
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Generous: the first paint waits on an image from artic.edu, over the internet, possibly
# through the proxy fallback. Everything after the first one is local.
FIRST_PAINT_MS = 30_000
SERVER_BOOT_SECONDS = 30


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
    return port


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """A real uvicorn on a free port, against a database of its own.

    Seeded from the bundled set, so the display has something to show without an AIC
    request. AI is left unconfigured, which is both the default and what flow 5 needs.
    """
    from app.domain.indexing import is_indexable
    from app.repositories.artwork_index import ArtworkIndexRepository
    from app.repositories.database import Database
    from app.repositories.preferences import PreferencesRepository
    from app.services.fallback import FallbackSet
    from app.services.selection import IIIF_BASE_KEY

    database_path = tmp_path_factory.mktemp("e2e") / "vitrine.db"
    database = Database(database_path)
    database.migrate()

    bundled = FallbackSet.load()
    ArtworkIndexRepository(database).upsert_many_sync(
        [artwork for artwork in bundled.artworks if is_indexable(artwork)]
    )
    # Without this the image proxy has no base until a live AIC response arrives, and on
    # an index-only start one never does.
    PreferencesRepository(database).set_sync(IIIF_BASE_KEY, bundled.iiif_base or "")

    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **_clean_env(),
            "DATABASE_PATH": str(database_path),
            "AI_ENABLED": "false",
            "AI_PROVIDER": "",
            "DEFAULT_LANGUAGE": "en",
            "DEFAULT_INTERVAL_SECONDS": "1800",
        },
    )

    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url, process)
        yield base_url
    finally:
        process.terminate()
        process.wait(timeout=10)


def _clean_env() -> dict[str, str]:
    """The developer's own environment, minus anything that would configure AI.

    A key in the shell would turn the feature on and flow 5 would silently stop testing
    what it says it tests.
    """
    import os

    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AI_", "ANTHROPIC_", "OPENAI_", "GEMINI_"))
    }


def _wait_for_health(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + SERVER_BOOT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the test server exited with {process.returncode}")
        try:
            if httpx.get(f"{base_url}/api/health", timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise TimeoutError(f"the test server did not come up within {SERVER_BOOT_SECONDS}s")


@pytest.fixture
def display(page: Page, server: str) -> Page:
    """The app, loaded, with one artwork actually painted.

    `naturalWidth`, not the `load` event and not `complete`: an `<img>` with no src at all
    reports complete, and a src that 404s reports it too once it has failed. The only
    thing that means a picture is on screen is that the bitmap has a width.
    """
    page.goto(server)
    page.wait_for_function(
        "() => document.getElementById('artwork').naturalWidth > 0", timeout=FIRST_PAINT_MS
    )
    return page


def current_image(page: Page) -> str:
    return str(page.locator("#artwork").get_attribute("src") or "")


VISIBLE = re.compile("visible")


class TestSmokeFlows:
    def test_the_app_loads_and_an_image_appears(self, display: Page):
        assert current_image(display), "no image was ever given a src"
        assert display.locator("#artwork").evaluate("img => img.naturalWidth") > 0

    def test_space_advances_to_a_different_artwork(self, display: Page):
        before = current_image(display)
        display.keyboard.press("Space")
        display.wait_for_function(
            "previous => document.getElementById('artwork').src !== previous"
            " && document.getElementById('artwork').naturalWidth > 0",
            arg=before,
            timeout=FIRST_PAINT_MS,
        )

    def test_i_opens_the_metadata_overlay(self, display: Page):
        """Pinned, not flashed. The overlay shows itself on every rotation and fades
        again; the only difference visible from outside is the confirmation, so that is
        what this waits for."""
        overlay = display.locator("#overlay")
        expect(overlay).not_to_have_class(VISIBLE, timeout=FIRST_PAINT_MS)

        display.keyboard.press("i")
        expect(overlay).to_have_class(VISIBLE)
        expect(display.locator("#status")).to_have_text("Details pinned")
        expect(display.locator("#ov-title")).not_to_be_empty()

    def test_the_language_switches_to_polish_and_back(self, display: Page):
        display.keyboard.press("s")
        expect(display.locator("#panel")).to_have_class(VISIBLE)

        display.locator('input[name="language"][value="pl"]').check()
        expect(display.locator(".panel-heading")).to_have_text("Ustawienia")
        # Screen readers and hyphenation key off this, so it is part of the switch.
        assert display.locator("html").get_attribute("lang") == "pl"

        display.locator('input[name="language"][value="en"]').check()
        expect(display.locator(".panel-heading")).to_have_text("Settings")
        assert display.locator("html").get_attribute("lang") == "en"

    def test_with_ai_disabled_the_overlay_shows_museum_data_and_no_error(self, display: Page):
        """The `CLAUDE.md` non-negotiable, checked where a user would see it break: the
        feature is not offered, and nothing on screen apologises for its absence."""
        display.keyboard.press("i")
        expect(display.locator("#ov-title")).not_to_be_empty()
        expect(display.locator("#ov-attribution")).to_contain_text("Art Institute of Chicago")
        # Hidden, not showing an error. Nothing was asked for, so there is nothing to
        # report — the frontend reads /api/health at boot precisely so it never asks.
        expect(display.locator("#ov-ai")).to_be_hidden()
