"""What the AI is allowed to produce, and how a produced thing is identified.

Pure. No provider, no HTTP, no SQLite — `providers/ai/` calls a model and hands the parsed
result here to be validated, and `repositories/` stores whatever survives that.

The point of validating into a fixed shape rather than keeping free text is the cache: a
shapeless cached value cannot be versioned, and a prompt change then leaves entries nobody
can reason about. Everything cached in this application has a declared shape.
"""

from typing import Final, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["en", "pl"]

CacheKind = Literal["interpretation", "visual"]
"""What a cached entry *is*. Two things go through the same cache and the same budget, and
they are not interchangeable: an interpretation says what an artwork might mean, a visual
description says what is in it, for somebody who cannot see it."""

# The separator in a cache key. A model identifier containing this would collide with a
# key built from different parts, so it is checked rather than assumed.
KEY_SEPARATOR: Final[str] = "|"


class Interpretation(BaseModel):
    """One validated interpretation of one artwork, in one language.

    A response that does not fit this is a cache miss, not an error the user sees. That
    distinction is the reason the bounds below are enforced rather than coerced: silently
    truncating six themes to five would hide a provider drifting away from its
    instructions, and the display has museum facts to fall back on either way.
    """

    model_config = ConfigDict(frozen=True)

    visual_description: str = Field(min_length=1)
    """What is literally visible. Grounded in the museum's own alt text where there is one."""

    interpretation: str = Field(min_length=1)
    """What it might mean. Hedged — the prompt asks for it and the display labels it."""

    themes: list[str] = Field(min_length=2, max_length=5)
    """Short phrases. Fewer than two is not a theme list; more than five is a model
    ignoring its instructions, which is worth noticing rather than trimming."""

    look_closer: str = Field(min_length=1)
    """One detail worth noticing. The line that earns the feature."""

    language: Language

    @field_validator("visual_description", "interpretation", "look_closer", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("themes", mode="before")
    @classmethod
    def _clean_themes(cls, value: object) -> object:
        """Drop blank entries before the length check.

        A trailing empty string is a formatting slip, not a different answer, and letting
        it count toward the minimum would accept a one-theme response.
        """
        if not isinstance(value, list):
            return value
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class VisualDescription(BaseModel):
    """A spoken-length account of what an artwork looks like, for a listener.

    **It is written from the museum's own words, not from the image.** No model here sees a
    picture. What grounds it is `thumbnail.alt_text` — written by a person at the Art
    Institute who did look at the artwork — plus the catalogue metadata, and the prompt's
    strongest instruction is to expand that rather than to invent past it. A blind listener
    cannot check a description against the artwork, which makes invented detail the one
    failure mode this feature must not have. `docs/ai-system.md` has the reasoning; the
    display says the same thing out loud, in both languages.

    Two fields because a listener needs an answer before they need an account: `summary` is
    the one sentence that says what is on screen, and `description` is what is read aloud.
    """

    model_config = ConfigDict(frozen=True)

    summary: str = Field(min_length=1, max_length=400)
    """One sentence. What the artwork is, at a glance."""

    description: str = Field(min_length=1, max_length=4000)
    """The spoken description itself: subject, composition, colour, scale, what sits where.
    Bounded because this is read aloud — past a few hundred words a listener has lost the
    beginning, and an unbounded field is an unbounded bill."""

    language: Language


CachedValue = Interpretation | VisualDescription
"""What may be stored. The `kind` on the key says which of the two a row holds, and the
cache validates into that model on the way out — so a row written under an older shape is a
miss rather than something the display trusts."""


class CacheKey(BaseModel):
    """Everything that can change an interpretation, and nothing that cannot.

    The provider and model are part of the key deliberately: two providers answering the
    same question do not produce interchangeable text, and an entry should not be served
    as though they did. ADR-0004 has the reasoning, and why a shared cache would need this
    to allow one entry to supersede another.
    """

    model_config = ConfigDict(frozen=True)

    artwork_id: int
    language: Language
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: int = Field(ge=1)

    kind: CacheKind = "interpretation"
    """Which of the two generated things this is. Appended to the key string only when it
    is not the default, so every interpretation cached before M14 keeps the key it was
    written under — a new field in a cache key is otherwise a silent, total invalidation,
    and this one would have thrown away work that is still perfectly good."""

    @field_validator("provider", "model")
    @classmethod
    def _reject_separator(cls, value: str) -> str:
        if KEY_SEPARATOR in value:
            # Two different keys could otherwise render identically, and the second one
            # would silently read the first one's text.
            raise ValueError(f"must not contain {KEY_SEPARATOR!r}")
        return value

    def as_string(self) -> str:
        """The primary key of the `interpretations` table."""
        parts = [
            str(self.artwork_id),
            self.language,
            self.provider,
            self.model,
            str(self.prompt_version),
        ]
        if self.kind != "interpretation":
            parts.append(self.kind)
        return KEY_SEPARATOR.join(parts)


class InterpretationCache(Protocol):
    """Somewhere a generated thing can be kept and found again.

    Named for what it held first. It holds visual descriptions too since M14, keyed by the
    same `CacheKey` with a different `kind` — renaming the Protocol and its two
    implementations would have been a wide, purely cosmetic change.

    Two implementations from day one — SQLite and a null shared cache — so the resolution
    chain in `docs/ai-system.md` is real code rather than a promise. ADR-0004 explains why
    the shared one is deliberately empty.

    Neither method may raise on a cache problem. A cache is an optimisation, and a corrupt
    one must degrade to a miss rather than take the display down.
    """

    name: str

    async def get(self, key: CacheKey) -> CachedValue | None: ...

    async def put(self, key: CacheKey, value: CachedValue) -> None: ...
