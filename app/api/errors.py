"""What a rejected request is allowed to say back.

FastAPI's own 422 body includes `input`: the value that failed validation, echoed to the
caller. That is helpful right up until the value is an API key — `PUT /api/ai/key` takes
one, and a key with a stray character in it would come straight back out in the error,
into the browser and into anything logging responses.

Found by a test that sent a malformed key and looked for it in the body, which is the
only way this kind of thing gets found: nothing about the code reads as a leak.

So the field is dropped, for every endpoint rather than one. The frontend keys its
messages off `detail` codes and has never read `input`, and an error body that cannot
carry a secret is worth more than one that explains itself in full.
"""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """A 422 that says what was wrong and where, but never what was sent.

    `ctx` goes too: for a `ValueError` raised in a validator it holds the exception
    object, and nothing stops a future validator from putting the value in its message.
    """
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
                for error in errors
            ]
        },
    )
