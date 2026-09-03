"""Never print a secret.

One function, in `core/` rather than beside any one provider, because the rule in
`docs/ai-system.md` is "redact to the last four characters everywhere" — logs, errors and
responses alike — and everywhere includes code that has nothing to do with AI.
"""

import re
from typing import Final

VISIBLE_CHARACTERS = 4
MASK = "…"

# Vendor API keys as they are actually shaped: a `sk-`-ish prefix and a long opaque tail.
# Deliberately narrow. This is a net under code that is already supposed to redact at the
# source, and a loose pattern that ate ordinary log text would make the logs worse while
# proving nothing.
_KEY_SHAPED: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9])(?:sk|rk|pk)[-_][A-Za-z0-9._-]{12,}"
)


def redact(secret: str | None) -> str:
    """Render a secret as its last four characters, or as nothing at all.

    A short secret shows none of itself: four characters out of six is most of it, and the
    point of this function is that its output is safe to write down.
    """
    if not secret:
        return ""
    if len(secret) <= VISIBLE_CHARACTERS * 2:
        return MASK
    return f"{MASK}{secret[-VISIBLE_CHARACTERS:]}"


def redact_secrets(text: str) -> str:
    """Replace anything key-shaped in a string with its redaction.

    The last line of defence for logs, applied to every record — see `core/logging.py`.
    Everything here that knows it is holding a key already calls `redact()`; this is for
    the line somebody writes next year that does not know it is.

    It cannot catch a key that does not look like one, so it is a net and not a policy.
    The policy is still: never put a secret in a log line.
    """
    return _KEY_SHAPED.sub(lambda match: redact(match.group(0)), text)
