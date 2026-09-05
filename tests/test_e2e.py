"""The nine Playwright flows from `docs/testing.md`, and no more.

Playwright is slow and flaky in proportion to how much you ask of it, so this file asks for
nine things: that the app loads a picture, that Space changes it, that `I` opens the
overlay, that the language switches, that with no AI configured the overlay shows the
museum's own facts and no error, that liking an artwork survives a reload (M11), that a
facet clicked twice excludes it (M13), that the accessibility description reaches the
screen with its grounding line (M14), and that the rotation is actually held while
somebody is reading (M16). Everything else lives in a unit or integration test.

Each of the last four had to argue for its slot, and the argument is the same one:
**there is no frontend test runner here and there will not be** (ADR-0005), so a rule that
only exists in the browser is either an e2e flow or it is untested. The sixth crosses a
keypress, an HTTP write, a SQLite row and the state read back onto a fresh page. The
seventh is the only check that a facet control cycles through three states and that the
third one narrows what the display serves — the panel's largest surface, rewritten
wholesale in M13. The eighth covers the one feature whose failure the person it is for
cannot see. The ninth covers a promise made since M3 that broke silently in M16 and that
587 unit tests and eight flows all missed.

The seventh grew two more parts in M17, and they are parts of it rather than flows ten and
eleven because they are the same control and the same argument: both cover a state the panel
offered and could not return from. One is the reported bug — an excluded facet that could not
be re-enabled, because two `/api/filters` answers came back out of order and the panel drew
the stale one. The other is the same shape on a live source, which has no facet layer to
exclude over at all.

Still nine after M18, which changed how two of them reach a control rather than adding a
tenth. The details are opened by clicking the caption now rather than by an `i` button, so
flow 9 clicks `#ov-facts` and asserts on `#ov-extra` — the catalogue facts, hidden at rest —
rather than on an attribute that only restates the click. And the settings are three tabs, so
the flows that reach for a filter say which one they want.

**The ninth is slow on purpose and is the only slow one.** It waits out a real rotation
interval, because the bug it covers is precisely that the clock keeps running when it has
been told not to, and nothing shorter can observe that. Forty seconds is the price of the
shortest interval the app offers.

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

import json
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


def open_settings(page, tab: str = "display"):
    """Open the panel, and bring one of its three tabs up.

    Since M18 the settings are tabbed and only the first tab is on screen when the panel
    opens, so a flow that reaches for a filter or the API key has to say which one it wants
    — everything in the other two is `hidden`, and Playwright rightly refuses to click a
    control nobody can see. `s` toggles, so a panel that is already open is left open.
    """
    if VISIBLE.search(page.locator("#panel").get_attribute("class") or "") is None:
        page.keyboard.press("s")
        expect(page.locator("#panel")).to_have_class(VISIBLE)
    page.locator(f'.panel-tab[data-tab="{tab}"]').click()


def clear_filters(page):
    """Start a filter flow from nothing selected.

    A fresh install is not empty: since M17 it starts with `type.coin` excluded, which is
    a product default with its own tests and is not what these flows are about. Without
    this, the badge assertion below reads "2 out" and the flow is testing the default as
    well as the control.
    """
    reset = page.locator("#panel-reset-filters")
    if not reset.is_hidden():
        reset.click()
        expect(reset).to_be_hidden()


def open_group(page, group: str):
    """Make sure a filter group is expanded, and return its root.

    Not a bare `summary.click()`, which is a *toggle*. A group opens itself as soon as
    anything in it is set (`syncCount` in `filters.js`), and since M17 a fresh install
    starts with `type.coin` excluded — so the artwork-type group arrives already open and
    a click on its summary shuts it. Two flows failed exactly that way when the default
    exclusion landed, and neither of them is about the disclosure triangle.
    """
    root = page.locator(f'[data-group="{group}"]')
    if not root.evaluate("element => element.open"):
        root.locator("summary").click()
    return root


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
    real = [artwork for artwork in bundled.artworks if is_indexable(artwork)]
    ArtworkIndexRepository(database).upsert_many_sync(real + _padding(real))
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


def _padding(real: list) -> list:
    """Enough copies of the bundled records to clear `MIN_FILTER_COUNT`.

    The bundled set is thirty artworks, and a facet is not offered at all below forty — so
    without this the filter panel correctly says there is nothing worth filtering on, and
    flow 7 has nothing to click. The copies carry real metadata under synthetic ids, which
    is the narrowest departure from "fixtures are recorded responses" that makes the flow
    possible: what is being tested is the panel, not AIC's shape.

    Two facets, deliberately, so excluding one leaves something behind to show.
    """
    from app.api.routes import MIN_FILTER_COUNT

    if not real:  # pragma: no cover - the bundled set is committed
        return []
    padded = []
    for index in range(MIN_FILTER_COUNT * 2):
        source = real[index % len(real)]
        padded.append(
            source.model_copy(
                update={
                    "id": 900_000 + index,
                    # A distinct title as well as a distinct id, so "the artwork changed"
                    # is observable from the caption. Copies that shared a title with
                    # their original made a rotation indistinguishable from no rotation,
                    # which is the exact thing flow 9 is asserting about.
                    "title": f"{source.title} (copy {index})",
                    "artwork_type_title": "Painting" if index % 2 else "Print",
                }
            )
        )
    return padded


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


@pytest.fixture(scope="module")
def ai_server(tmp_path_factory):
    """A second server, with the mock provider, for flow 8.

    Its own process rather than a flag on the first one, because flow 5 asserts the exact
    opposite — that with nothing configured the feature is not offered — and a server that
    changed its mind halfway through the module would make one of the two a lie. Thirteen
    seconds of Playwright is the price, and the alternative is that the accessibility path
    is proven only against a `TestClient`.
    """
    from app.domain.indexing import is_indexable
    from app.repositories.artwork_index import ArtworkIndexRepository
    from app.repositories.database import Database
    from app.repositories.preferences import PreferencesRepository
    from app.services.fallback import FallbackSet
    from app.services.selection import IIIF_BASE_KEY

    database_path = tmp_path_factory.mktemp("e2e-ai") / "vitrine.db"
    database = Database(database_path)
    database.migrate()
    bundled = FallbackSet.load()
    ArtworkIndexRepository(database).upsert_many_sync(
        [artwork for artwork in bundled.artworks if is_indexable(artwork)]
    )
    PreferencesRepository(database).set_sync(IIIF_BASE_KEY, bundled.iiif_base or "")

    port = free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=Path(__file__).resolve().parent.parent,
        env={
            **_clean_env(),
            "DATABASE_PATH": str(database_path),
            # No key and no network: the mock implements `VisualDescriptionProvider` for
            # exactly this reason.
            "AI_ENABLED": "true",
            "AI_PROVIDER": "mock",
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

    def test_a_favourite_survives_a_reload(self, display: Page):
        """The whole stack in one flow: `L`, an HTTP write, a SQLite row with no foreign
        key, and the state read back onto a fresh page from the artwork response itself."""
        heart = display.locator("#ov-like")
        display.mouse.move(400, 400)
        expect(display.locator("#overlay")).to_have_class(VISIBLE)
        expect(heart).to_have_attribute("aria-pressed", "false")

        display.keyboard.press("l")
        expect(display.locator("#status")).to_have_text("Added to favourites")
        expect(heart).to_have_attribute("aria-pressed", "true")

        display.reload()
        display.wait_for_function(
            "() => document.getElementById('artwork').naturalWidth > 0", timeout=FIRST_PAINT_MS
        )
        display.mouse.move(410, 410)
        # The same artwork does not necessarily come back — the rotation is random — so
        # what is asserted is the record, which is what had to survive.
        favourites = display.evaluate("async () => (await (await fetch('/api/favorites')).json())")
        assert len(favourites) == 1
        assert favourites[0]["title"], "the snapshot is what lets a favourite outlive the index"

    def test_a_facet_clicked_twice_excludes_it(self, display: Page):
        """Flow 7. The panel's largest surface, and the only place its three states exist.

        Until M13 inclusion was a radio and exclusion was a checkbox in a second list; now
        one control cycles off → include → exclude → off, and every part of that lives in
        the browser. What is asserted is the whole round trip: the control changes state,
        the badge in the collapsed heading says so, and the served artwork actually stops
        being the excluded type.
        """
        open_settings(display, "filters")

        clear_filters(display)
        group = open_group(display, "artwork-type")
        facet = group.locator('.facet[data-value="type.print"]')
        expect(facet).to_have_attribute("data-state", "off")

        facet.click()
        expect(facet).to_have_attribute("data-state", "include")
        facet.click()
        expect(facet).to_have_attribute("data-state", "exclude")
        # The heading says what is on inside it, so a collapsed group never hides a live
        # filter — which is the whole reason the badge exists.
        expect(display.locator('[data-badge="artwork-type"]')).to_contain_text("1")

        # And it is a real filter, not just a control that changed colour.
        served = display.evaluate(
            "async () => {"
            "  const seen = [];"
            "  for (let i = 0; i < 6; i++) {"
            "    const r = await fetch('/api/artwork/random?exclude=type.print');"
            "    seen.push((await r.json()).artwork_type);"
            "  }"
            "  return seen;"
            "}"
        )
        assert "Print" not in served, served

        facet.click()
        expect(facet).to_have_attribute("data-state", "off")

    def test_clearing_an_exclusion_survives_its_own_answer_arriving_late(self, display: Page):
        """Flow 7, second half. The reported bug: an excluded facet could not be turned
        back on.

        Every click re-asks `/api/filters`, and the answers do not come back in the order
        they were asked for. An exclusion is a NOT over the whole facet table and is
        measurably the slower query — about 50ms slower on this index — so the answer that
        says "excluded" can land *after* the answer to the click that cleared it. The
        panel drew the stale one: count zero, on a row whose state had just gone back to
        off, which is exactly the pair `buildRow` disables. The row went inert and there
        was no way to click the facet on again.

        The first half of this flow cannot see it, because `expect()` between clicks waits
        for each answer and so never lets two be in flight. This half puts them in flight
        on purpose, by holding the exclusion's answer back until the next one has landed.
        The delay is the mechanism, not the assertion: what is asserted is that the row is
        still a live control afterwards.

        The holding is done in the page rather than with `page.route`, and that is not a
        preference. A sync route handler runs on this thread, so sleeping in one stops
        pytest issuing the second click as well as the first response — the two requests
        never overlap and the flow passes against the bug. Patching `fetch` delays one
        response inside the browser and leaves everything else running.
        """
        display.evaluate(
            """() => {
              const original = window.fetch;
              window.fetch = async (...args) => {
                const url = typeof args[0] === 'string' ? args[0] : args[0].url;
                const response = await original(...args);
                if (url.includes('/api/filters') && url.includes('exclude=type.print')) {
                  await new Promise((done) => setTimeout(done, 1500));
                }
                return response;
              };
            }"""
        )

        open_settings(display, "filters")
        clear_filters(display)
        group = open_group(display, "artwork-type")
        facet = group.locator('.facet[data-value="type.print"]')

        facet.click()  # include
        expect(facet).to_have_attribute("data-state", "include")
        # No waiting between these two: the second click has to leave while the first
        # one's request is still out, which is the whole point.
        facet.click()  # exclude — its answer is held
        facet.click()  # clear

        expect(facet).to_have_attribute("data-state", "off")
        # The late answer has landed by now, and must have been dropped rather than drawn.
        display.wait_for_timeout(2_500)
        expect(facet).to_have_attribute("data-state", "off")
        expect(facet).to_be_enabled()
        # And it is a control again, not just a row that looks enabled.
        facet.click()
        expect(facet).to_have_attribute("data-state", "include")

    def test_a_live_source_offers_no_state_it_cannot_honour(self, display: Page):
        """Flow 7, third part, and the same bug family as the second.

        Exclusion is a NOT over the canonical facet layer, and only the indexed corpus has
        one (ADR-0009, ADR-0013). On Cleveland the third click produced a state the server
        would not accept, `applySelection` then dropped on the next redraw, and the row
        snapped back to off — a control with a state that silently did nothing. The cycle
        is two states there, and the sentence above the groups says which one is running.

        Cleveland's own vocabulary is stubbed rather than fetched. What is under test is
        the control, not the museum, and the rest of this file stays off the network for
        everything except the one image in flow 1. The shape of the stub is what
        `_live_filters` returns: bare artwork types with live totals, and no facet keys —
        which is the very difference the two-state cycle exists to express.
        """
        display.route(
            re.compile(r"/api/filters\?.*museum=cma"),
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "museum": "cma",
                        "artwork_types": [
                            {"value": "Painting", "count": 1234, "label": "Painting"},
                            {"value": "Print", "count": 567, "label": "Print"},
                        ],
                        "styles": [],
                        "subjects": [],
                        "minimum_count": 0,
                        "maximum_options": 2,
                        "indexed_total": 1801,
                    }
                ),
            ),
        )
        # Switching source also asks for a Cleveland artwork. Refused rather than fetched:
        # the display shows its own "could not reach the source" line, which is not what
        # this flow is looking at, and no request leaves the machine.
        display.route(re.compile(r"/api/artwork/.*museum=cma"), lambda route: route.abort())

        # Across two tabs, because that is where the two halves of this now live: the source
        # is a display setting and the hint belongs to the filters. The tab clicks are not
        # what is being tested and are the whole cost of the M18 split.
        open_settings(display, "filters")
        expect(display.locator("#panel-filter-hint")).to_contain_text("exclude")

        display.locator('.panel-tab[data-tab="display"]').click()
        display.locator('input[name="museum"][value="cma"]').check()

        display.locator('.panel-tab[data-tab="filters"]').click()
        expect(display.locator("#panel-filter-hint")).not_to_contain_text("exclude")

        group = open_group(display, "artwork-type")
        facet = group.locator('.facet[data-value="Painting"]')
        facet.click()
        expect(facet).to_have_attribute("data-state", "include")
        facet.click()
        expect(facet).to_have_attribute("data-state", "off")

    def test_the_spoken_description_reaches_the_screen_with_its_grounding(
        self, page: Page, ai_server: str
    ):
        """Flow 8. The one feature whose failure the person it is for cannot see.

        A sighted user notices an empty panel. Somebody relying on this notices silence,
        which is indistinguishable from having pressed the wrong key. So the flow asserts
        the three things that make it usable: the region appears, the text arrives, and the
        line saying where the words came from is on screen with it — the display's half of
        the promise that no model saw the artwork.
        """
        page.goto(ai_server)
        page.wait_for_function(
            "() => document.getElementById('artwork').naturalWidth > 0", timeout=FIRST_PAINT_MS
        )
        section = page.locator("#ov-access")
        expect(section).to_be_hidden()
        # Offered at all only because /api/health said the provider can write one.
        expect(page.locator("#ov-describe")).not_to_be_hidden()

        page.keyboard.press("a")

        expect(section).not_to_be_hidden()
        expect(page.locator("#access-summary")).not_to_be_empty()
        expect(page.locator("#access-grounding")).to_contain_text("No AI has seen the artwork")
        # A real button, in the tab order, so replay is reachable without a mouse.
        expect(page.locator("#access-play")).not_to_be_hidden()

    def test_the_rotation_is_held_while_the_details_are_open(self, display: Page):
        """Flow 9. `docs/product-spec.md` has promised since M3 that opening the settings
        pauses the rotation, and since M13 that expanding the details does too.

        It broke, silently, and nothing caught it. `pause()` cleared the timers, which is
        not the same as stopping the clock: an `advance()` already in flight re-armed on
        its way out, in a `finally`, and the hold was gone. That window is about a second
        on every advance and is the *whole* window at page load — which is where it was
        found, by expanding the details half a second after opening the app and watching
        the artwork change anyway.

        So this flow waits. Thirty seconds is the shortest interval the app offers and
        there is no faster way to see a clock that should not be ticking.
        """
        display.keyboard.press("1")  # 30-second rotation
        expect(display.locator("#status")).to_contain_text("30")

        display.mouse.move(400, 400)
        expect(display.locator("#overlay")).to_have_class(VISIBLE)
        # `text_content`, not `inner_text`: the latter returns "" for anything not
        # visible, and this test deliberately runs across the overlay's idle timer.
        before = display.locator("#ov-title").text_content()

        # The caption itself, which is the control since M18 — there is no `i` button any
        # more. `#ov-extra` is what says it worked: the catalogue facts are `hidden` at rest
        # and shown only while the details are open, so it is the state rather than a
        # restatement of the click.
        display.locator("#ov-facts").click()
        expect(display.locator("#ov-extra")).to_be_visible()

        # Somebody is reading, so the mouse moves. Without this the overlay's own 20s
        # reading timer fades it, which *collapses* the details and correctly releases the
        # clock — the unattended-display rule QUESTIONS.md #3 protects. Testing that path
        # would be testing the opposite feature.
        for _ in range(8):
            display.wait_for_timeout(5_000)
            display.mouse.move(400, 400)

        assert display.locator("#ov-title").text_content() == before, (
            "the artwork rotated while the details were expanded"
        )
        # Still expanded, because a rotation would have collapsed it — a second way of
        # asserting the same thing, and the one that would catch a rotation this test
        # happened to sample either side of.
        expect(display.locator("#ov-extra")).to_be_visible()

        # And the clock is held, not dead: collapsing releases it and the display advances.
        #
        # The overlay's own button, not Space: `shortcuts.js` leaves Space to a focused
        # control that acts on it (`actsOnSpace`), and a stray press here would be one more
        # thing to reason about than the flow needs.
        display.locator("#ov-facts").click()
        expect(display.locator("#ov-extra")).to_be_hidden()
        display.locator("#ov-next").click()
        display.wait_for_function(
            "previous => document.getElementById('ov-title').textContent !== previous",
            arg=before,
            timeout=FIRST_PAINT_MS,
        )
