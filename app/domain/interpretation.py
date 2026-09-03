"""What the AI is allowed to produce, and how a produced thing is identified.

Pure. No provider, no HTTP, no SQLite — `providers/ai/` calls a model and hands the parsed
result here to be validated, and `repositories/` stores whatever survives that.

The point of validating into a fixed shape rather than keeping free text is the cache: a
shapeless cached value cannot be versioned, and a prompt change then leaves entries nobody
can reason about. Everything cached in this application has a declared shape.
"""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["en", "pl"]

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
        return KEY_SEPARATOR.join(
            [
                str(self.artwork_id),
                self.language,
                self.provider,
                self.model,
                str(self.prompt_version),
            ]
        )
