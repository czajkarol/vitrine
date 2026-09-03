"""The HTTP plumbing both real providers turned out to need.

Extracted when the second provider arrived, because it wanted the same four things as the
first: a client with the configured timeout, a POST, an error map from httpx's exceptions
and status codes onto `ProviderUnavailableError`, and a guarantee that the key appears in
no message.

Shared *implementation*, deliberately not part of the interface in `base.py`. A provider
that needs a different transport — a vendor SDK, a streaming socket — implements
`InterpretationProvider` without this and nothing else has to know.
"""

from typing import Any, Final

import httpx

from app.core.redaction import redact
from app.providers.ai.base import InvalidResponseError, ProviderUnavailableError

JSON_CONTENT_TYPE: Final[str] = "application/json"


class ProviderHttp:
    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        timeout_seconds: float,
        headers: dict[str, str],
    ) -> None:
        self._name = name
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"content-type": JSON_CONTENT_TYPE, **headers},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST and return the decoded body, or raise a provider error.

        Every failure mode of the transport ends up as `ProviderUnavailableError`, which
        is what the circuit breaker counts. An invalid key is not transient and still
        arrives here — but it fails identically, and a breaker that stops after five
        identical 401s is the right outcome for that too.
        """
        try:
            response = await self._client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"{self._name} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{self._name} unreachable: {exc}") from exc

        if response.status_code >= 400:
            raise ProviderUnavailableError(
                f"{self._name} returned {response.status_code} for key "
                f"{redact(self._api_key)}: {_error_message(response)}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise InvalidResponseError(f"{self._name} returned a non-JSON body") from exc

        if not isinstance(body, dict):
            raise InvalidResponseError(
                f"{self._name} returned {type(body).__name__}, not an object"
            )
        return body


def _error_message(response: httpx.Response) -> str:
    """The provider's own explanation, if it gave one worth repeating."""
    try:
        error = response.json().get("error", {})
        message = error.get("message", "") if isinstance(error, dict) else ""
        return str(message)[:200]
    except ValueError:
        return response.text[:200]
