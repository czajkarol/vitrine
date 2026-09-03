"""Never print a secret.

One function, in `core/` rather than beside any one provider, because the rule in
`docs/ai-system.md` is "redact to the last four characters everywhere" — logs, errors and
responses alike — and everywhere includes code that has nothing to do with AI.
"""

VISIBLE_CHARACTERS = 4
MASK = "…"


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
