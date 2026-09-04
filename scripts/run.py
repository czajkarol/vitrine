#!/usr/bin/env python
"""Start the server and open the display in a browser.

    uv run python scripts/run.py
    uv run python scripts/run.py --port 8001
    uv run python scripts/run.py --no-browser

`uv run uvicorn app.main:app --reload` does the same thing minus the last step. uvicorn
starts, prints a URL and waits; it has no option to open a page and never has. So a
successful start is `Application startup complete.` followed by a terminal that sits there,
which is indistinguishable from a hang if you are waiting for a window to appear. This waits
for `/api/health` to answer and then opens the page, so a start that worked looks like one.

Two failure paths it handles rather than passing on:

- **vitrine is already running on that port.** Opens the running one instead of dying on a
  bind error. Starting it twice is the common case, not a mistake worth an error message.
- **Something else holds the port.** Says so, and says how to find it. `netstat` attributes a
  listening socket to the process that created it and keeps doing so after that process has
  exited, as long as a child still holds the inherited handle — which is what `--reload`
  leaves behind when its parent is killed without Ctrl+C. The process list is the truth there;
  the socket table will name a PID that no longer exists.

No network beyond the loopback probe. This starts a local server.
"""

import argparse
import functools
import logging
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path

# Running this as a script rather than a module, so the package has to be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

logger = logging.getLogger("run")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# The startup this waits out is an import of the app and a SQLite connection, which is well
# under a second warm. The ceiling is generous because the cost of overshooting is a browser
# tab opening a moment late, and the cost of undershooting is the confusion this exists to
# remove. A probe is one loopback connection to a port on this machine.
READY_ATTEMPTS = 60
READY_DELAY_SECONDS = 0.25
PROBE_TIMEOUT_SECONDS = 1.0


def responds(url: str, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """True when `url` answers with a 2xx. Any failure to reach it is a False, not a raise.

    Every reason a probe fails — nothing listening yet, connection refused mid-startup, a
    socket that accepts and then hangs up — means the same thing to the caller: not ready.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def port_is_taken(host: str, port: int) -> bool:
    """True when a server cannot be started on `host:port` because something holds it.

    Asked only after `responds` has said no, to tell "the port is free" apart from "the port
    is held by something that is not vitrine". Those need different advice.

    Tries the bind rather than a connection, because the question is whether uvicorn can
    start here, and that is a bind. A connection test answers a different question and gets
    this one wrong: a listener whose accept queue is full refuses the connection and reads as
    a free port, which sends the caller on to a bind that then fails.

    Deliberately no SO_REUSEADDR. On Windows it lets one process bind a port another already
    holds, which would report a taken port as free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return True
    return False


def wait_until_ready(
    probe: Callable[[], bool],
    *,
    attempts: int = READY_ATTEMPTS,
    delay: float = READY_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll `probe` until it is True. False if it never was within `attempts`."""
    for remaining in range(attempts, 0, -1):
        if probe():
            return True
        if remaining > 1:
            sleep(delay)
    return False


def open_when_ready(
    url: str,
    probe: Callable[[], bool],
    *,
    open_page: Callable[[str], object] = webbrowser.open,
    attempts: int = READY_ATTEMPTS,
    delay: float = READY_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Open `url` once the server answers, or explain why it was not opened.

    Runs on a thread beside the server, so giving up has to be said out loud: the terminal
    is showing uvicorn's log and nothing else would mark the absence of a browser tab.
    """
    if wait_until_ready(probe, attempts=attempts, delay=delay, sleep=sleep):
        logger.info("Opening %s", url)
        open_page(url)
    else:
        logger.warning(
            "The server did not answer within %.0fs, so no page was opened. "
            "Open %s yourself once the log says startup is complete.",
            attempts * delay,
            url,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Start vitrine and open the display in a browser.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default: {DEFAULT_PORT}")
    parser.add_argument(
        "--no-browser", action="store_true", help="start the server without opening a page"
    )
    parser.add_argument(
        "--no-reload", action="store_true", help="do not restart when a source file changes"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    url = f"http://{args.host}:{args.port}"
    probe = functools.partial(responds, f"{url}/api/health")

    if probe():
        # ASCII only in anything printed here. The Windows console this is most often run in
        # is a legacy code page, and an em dash arrives as a replacement character.
        logger.info("vitrine is already running at %s, so opening that one.", url)
        if not args.no_browser:
            webbrowser.open(url)
        return

    if port_is_taken(args.host, args.port):
        raise SystemExit(
            f"Something is already listening on {args.host}:{args.port}, and it does not "
            f"answer as vitrine.\n\n"
            f"Find it by process rather than by socket. netstat will name the PID that "
            f"opened the port even after that process has exited:\n\n"
            f"    Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |\n"
            f"        Select-Object ProcessId,CreationDate,CommandLine\n\n"
            f"Or leave it alone and use another port: --port {args.port + 1}"
        )

    if not args.no_browser:
        # Daemon, so Ctrl+C at the server is the end of both. The reloader spawns the server
        # in a child process and this thread stays in the parent, so the page opens once at
        # startup rather than again on every edit.
        threading.Thread(target=open_when_ready, args=(url, probe), daemon=True).start()

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=not args.no_reload)


if __name__ == "__main__":
    main()
