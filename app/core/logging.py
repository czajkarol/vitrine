"""Logging setup: one request id on every line, and no secrets on any of them.

Two formats. `text` is the default because this app is run from a terminal by the person
who owns it, and a wall of JSON is worse than useless there. `json` exists for when the
logs are being shipped somewhere that wants to parse them, and is one line per record with
the same fields.

The request id is a `ContextVar`, not a parameter. Every warning this app already emits —
an image that would not load, a provider that timed out, a preference that would not
validate — was written before there was such a thing as a request id, and threading one
through all of them would have been a worse change than reading it from the context at
format time.
"""

import json
import logging
import uuid
from contextvars import ContextVar
from typing import Final, Literal

from app.core.redaction import redact_secrets

LogFormat = Literal["text", "json"]

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
"""`-` rather than empty for anything logged outside a request: startup, shutdown, the
indexing script. A dash lines up in a column; an empty string does not."""


def new_request_id() -> str:
    """Short enough to read in a terminal, long enough not to collide in a day's logs."""
    return uuid.uuid4().hex[:8]


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attach the current request id, and redact anything key-shaped in the message.

    A filter rather than a formatter so both formats get it, and so the redaction happens
    once, before any handler sees the record. `record.msg` is rewritten rather than the
    formatted output because a `%s` argument is where a key would actually arrive.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        # Formatting here rather than leaving msg/args to the handler: a key passed as an
        # argument is not visible in `msg` alone, and this has to see the finished text.
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Deliberately flat — no nesting to unwrap."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


TEXT_FORMAT: Final[str] = "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s"


def configure(level: str, log_format: LogFormat = "text") -> None:
    """Install the root handler. Called once, from the app's lifespan.

    Replaces any handler already there rather than adding to it, because uvicorn installs
    its own and two handlers means every line twice.
    """
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if log_format == "json" else logging.Formatter(TEXT_FORMAT)
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _adopt_uvicorn()


def _adopt_uvicorn() -> None:
    """Make uvicorn's own lines go through this handler too.

    Its loggers carry their own handler and do not propagate, so without this the startup
    banner and any server error come out in a different format from everything else — and
    in `json` mode, they come out as prose in the middle of a stream of objects.

    Its access log is silenced rather than adopted: the middleware already logs one line
    per API request, with the request id and the duration, and two lines per request is
    how a log stops being read.
    """
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = True
    access.setLevel(logging.WARNING)
