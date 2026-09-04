"""Tests for `scripts/run.py`, the launcher that opens a browser once the server answers.

The launcher exists because a successful uvicorn start looks like a hang. Its logic is the
waiting: how long to poll, when to stop, and whether to open a page at the end. That is what
is tested here. Starting an actual server is uvicorn's job and is covered by the e2e fixture.

Nothing here reaches past the loopback interface. The two socket fixtures bind a port on this
machine to give `responds` and `port_is_taken` something real to look at, because a probe that
is only ever handed a fake cannot show that it swallows the errors it is supposed to swallow.
"""

import importlib.util
import logging
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_launcher() -> ModuleType:
    """Import `scripts/run.py` by path. `scripts/` is not a package and should not become one."""
    spec = importlib.util.spec_from_file_location(
        "vitrine_launcher", REPO_ROOT / "scripts" / "run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


run = _load_launcher()


@pytest.fixture
def listening_port() -> Iterator[int]:
    """A port with a socket accepting connections but never answering."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        yield int(server.getsockname()[1])


@pytest.fixture
def closed_port() -> int:
    """A port number nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def answers_after(failures: int) -> Callable[[], bool]:
    """A probe that is False `failures` times and True from then on."""
    remaining = [failures]

    def probe() -> bool:
        if remaining[0] > 0:
            remaining[0] -= 1
            return False
        return True

    return probe


class TestWaitUntilReady:
    def test_a_server_that_is_already_up_is_not_waited_for(self) -> None:
        naps: list[float] = []

        assert run.wait_until_ready(answers_after(0), attempts=5, sleep=naps.append) is True
        assert naps == []

    def test_it_keeps_polling_until_the_server_answers(self) -> None:
        naps: list[float] = []

        ready = run.wait_until_ready(answers_after(3), attempts=10, delay=0.25, sleep=naps.append)

        assert ready is True
        assert naps == [0.25, 0.25, 0.25]

    def test_it_gives_up_after_the_last_attempt(self) -> None:
        assert run.wait_until_ready(lambda: False, attempts=4, sleep=lambda _: None) is False

    def test_it_does_not_sleep_after_the_attempt_it_gives_up_on(self) -> None:
        # Four attempts are separated by three waits, not four. The last one buys nothing —
        # it is time spent between deciding to give up and saying so.
        naps: list[float] = []

        run.wait_until_ready(lambda: False, attempts=4, delay=0.25, sleep=naps.append)

        assert naps == [0.25, 0.25, 0.25]


class TestOpenWhenReady:
    def test_the_page_opens_once_the_server_answers(self) -> None:
        opened: list[str] = []

        run.open_when_ready(
            "http://127.0.0.1:8000",
            answers_after(2),
            open_page=opened.append,
            attempts=5,
            sleep=lambda _: None,
        )

        assert opened == ["http://127.0.0.1:8000"]

    def test_no_page_opens_when_the_server_never_answers(self) -> None:
        opened: list[str] = []

        run.open_when_ready(
            "http://127.0.0.1:8000",
            lambda: False,
            open_page=opened.append,
            attempts=3,
            sleep=lambda _: None,
        )

        assert opened == []

    def test_giving_up_is_said_out_loud(self, caplog: pytest.LogCaptureFixture) -> None:
        # The thread this runs on has no other way to report itself. Silence here reads as
        # the same hang the launcher was written to remove.
        with caplog.at_level(logging.WARNING, logger="run"):
            run.open_when_ready(
                "http://127.0.0.1:8000",
                lambda: False,
                open_page=lambda _: None,
                attempts=2,
                sleep=lambda _: None,
            )

        assert "http://127.0.0.1:8000" in caplog.text


class TestProbes:
    def test_nothing_listening_is_a_false_rather_than_a_raise(self, closed_port: int) -> None:
        assert run.responds(f"http://127.0.0.1:{closed_port}/api/health", timeout=0.5) is False

    def test_a_socket_that_accepts_and_never_answers_is_also_a_false(
        self, listening_port: int
    ) -> None:
        # Mid-startup a port can be bound before the app can serve. A read timeout has to
        # mean "not ready yet", the same as a refused connection.
        assert run.responds(f"http://127.0.0.1:{listening_port}/api/health", timeout=0.3) is False

    def test_a_listening_socket_is_seen_as_holding_the_port(self, listening_port: int) -> None:
        assert run.port_is_taken("127.0.0.1", listening_port) is True

    def test_a_free_port_is_seen_as_free(self, closed_port: int) -> None:
        assert run.port_is_taken("127.0.0.1", closed_port) is False

    def test_a_listener_with_a_full_accept_queue_still_holds_the_port(
        self, listening_port: int
    ) -> None:
        # The fixture's backlog is one and it never accepts, so this connection fills it and
        # the next connection attempt is refused. A port_is_taken written as a connection test
        # reads that refusal as a free port and sends the caller on to a bind that fails. It
        # is not a hypothetical: it is how the occupied-port path was first found to be wrong.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as filler:
            filler.settimeout(1.0)
            filler.connect(("127.0.0.1", listening_port))

            assert run.port_is_taken("127.0.0.1", listening_port) is True
