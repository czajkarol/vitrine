"""One request id per request, from the first log line to the response header.

An inbound `X-Request-ID` is honoured — a reverse proxy or a script may already have one,
and two ids for the same request is worse than no id at all. Anything else gets a fresh
one, and it goes back out on the response so a user reporting "it did the thing at 19:32"
has something to hand over.

Only `/api` requests are logged. Static files are served by `StaticFiles` and there are
hundreds of them at boot; a line each would bury the twenty that mean something.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.core.logging import REQUEST_ID_HEADER, get_request_id, new_request_id, set_request_id

logger = logging.getLogger("app.api.access")

CallNext = Callable[[Request], Awaitable[Response]]

# Ids from outside are put in a log line and a header, so they are length-capped and
# stripped of anything that would let a caller forge a line or an extra header.
MAX_INBOUND_ID_LENGTH = 64


async def request_id_middleware(request: Request, call_next: CallNext) -> Response:
    set_request_id(_inbound_id(request) or new_request_id())

    started = time.monotonic()
    response = await call_next(request)
    elapsed_ms = (time.monotonic() - started) * 1000

    if request.url.path.startswith("/api"):
        # Path without the query string: nothing here takes a secret in a query today, and
        # logging the whole URL is how that stops being true without anyone noticing.
        logger.info(
            "%s %s -> %d in %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

    response.headers[REQUEST_ID_HEADER] = get_request_id()
    return response


def _inbound_id(request: Request) -> str | None:
    candidate = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if not candidate or len(candidate) > MAX_INBOUND_ID_LENGTH:
        return None
    if not all(character.isalnum() or character in "-_" for character in candidate):
        return None
    return candidate
