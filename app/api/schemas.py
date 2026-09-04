"""HTTP response shapes. Serialisation only — no logic lives here."""

from typing import Final, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator

from app.domain.artwork import Artwork


class ArtworkResponse(BaseModel):
    """One artwork, shaped for the display.

    The IIIF base and the image id are sent separately rather than as a finished URL:
    only the browser knows its viewport and pixel ratio, so only the browser can pick the
    width. See `docs/architecture.md`.
    """

    id: int
    title: str
    artist: str | None
    artist_display: str | None
    date_display: str | None
    medium_display: str | None
    credit_line: str | None
    place_of_origin: str | None
    main_reference_number: str | None

    description: str | None
    """CC BY 4.0. If this is shown, AIC must be attributed alongside it."""

    iiif_base: str
    """Empty for a source with no IIIF service. Cleveland has none — three fixed URLs per
    record and no ladder — so the display falls back to `image_url`. ADR-0013."""

    image_id: str
    image_url: str | None = None
    """A ready-made image URL, for a source that cannot build one from a base and an id.
    When this is set the browser uses it as-is: there is no width to choose and no proxy
    to fall back to."""

    museum: str = "aic"
    """Which museum this came from. Distinct from `source`, which says which *tier*
    answered. The attribution line and the feedback key both depend on it."""

    lqip: str | None
    alt_text: str | None
    source_width: int | None
    source_height: int | None
    color: dict[str, float] | None
    is_boosted: bool

    source: str = "aic"
    """Which tier produced this: index, aic, or fallback. The display shows a quiet
    offline indicator when it is not the live API."""

    feedback: Literal["like", "dislike", "hide"] | None = None
    """The verdict already recorded for this artwork, if any. Sent with the artwork rather
    than fetched separately, because the display needs it on every rotation and it is one
    indexed lookup — a second round trip per artwork to draw a heart is not worth it."""

    liked: bool = False
    """Kept alongside `feedback` because it is what the heart binds to, and because a
    boolean is what a stored e2e expectation and any older client reads."""

    personalised: bool = False
    """Whether "For you" actually personalised this one, or fell back to curated ranking
    for want of enough likes. The display says which — a recommendation that is not one is
    worse than no recommendation."""

    @classmethod
    def from_domain(
        cls,
        artwork: Artwork,
        iiif_base: str,
        source: str = "aic",
        museum: str = "aic",
        image_url: str | None = None,
    ) -> "ArtworkResponse":
        if artwork.image_id is None:  # pragma: no cover — guarded by is_displayable
            raise ValueError("artwork has no image_id and should not have been selected")
        thumbnail = artwork.thumbnail
        colour = artwork.color
        return cls(
            id=artwork.id,
            title=artwork.title,
            artist=artwork.artist_title,
            artist_display=artwork.artist_display,
            date_display=artwork.date_display,
            medium_display=artwork.medium_display,
            credit_line=artwork.credit_line,
            place_of_origin=artwork.place_of_origin,
            main_reference_number=artwork.main_reference_number,
            description=artwork.description,
            iiif_base=iiif_base,
            image_id=artwork.image_id,
            lqip=thumbnail.lqip if thumbnail else None,
            alt_text=thumbnail.alt_text if thumbnail else None,
            source_width=thumbnail.width if thumbnail else None,
            source_height=thumbnail.height if thumbnail else None,
            color=({"h": colour.h, "s": colour.s, "l": colour.l} if colour is not None else None),
            is_boosted=artwork.is_boosted,
            source=source,
            museum=museum,
            image_url=image_url,
        )


class ErrorResponse(BaseModel):
    """A machine-readable failure. `code` is what the frontend keys its message off."""

    code: str
    detail: str


MAX_EXCLUSIONS: Final[int] = 20
"""How many facets one selection may exclude. Twenty is far more than anyone will use and
still bounds the `NOT IN (...)` this becomes."""

MAX_INCLUSIONS: Final[int] = 20
"""And how many one group may include. Same reasoning, applied to the other half of the
filter once M13 made inclusion multi-valued."""

MUSEUMS: Final[tuple[str, ...]] = ("aic", "cma")
"""The sources the display can be pointed at. `aic` is the indexed corpus; `cma` is served
live. ADR-0013."""


class PreferencesResponse(BaseModel):
    """The preferences the user can actually set.

    A typed shape rather than a free key/value passthrough: the `preferences` table also
    holds things the app learned for itself — the IIIF base, the crawler's progress — and
    those are not the browser's to write.
    """

    # Seconds, not minutes: the menu has a 30-second rung and the unit has to hold the
    # shortest one it offers. 30s / 1m / 5m / 15m / 30m.
    interval_seconds: Literal[30, 60, 300, 900, 1800] = 300
    mode: Literal["random", "curated", "personal"] = "random"
    # Canonical facet keys since M10 — `type.print`, not `Print` (ADR-0009). Lists since
    # M13: several values inside a group are ORed, which is what ticking two boxes means.
    # Radios were right while inclusion was ANDed and are wrong now — ADR-0014.
    artwork_type: list[str] = Field(default_factory=list, max_length=MAX_INCLUSIONS)
    style: list[str] = Field(default_factory=list, max_length=MAX_INCLUSIONS)
    subject: list[str] = Field(default_factory=list, max_length=MAX_INCLUSIONS)
    # Exclusion. NOT-ed over every group at once, so unlike the three above it is one flat
    # list. Capped so a saved preference cannot grow into a query with a thousand
    # placeholders in it.
    exclude: list[str] = Field(default_factory=list, max_length=MAX_EXCLUSIONS)
    # Which museum the display is drawing from. Persisted like any other choice: a display
    # left on Cleveland should still be on Cleveland after a reload.
    museum: Literal["aic", "cma"] = "aic"
    # Only the languages frontend/locales/ actually has strings for. The default is
    # overridden by `default_language` when nothing has been saved yet.
    language: Literal["en", "pl"] = "en"
    # Screen Wake Lock. Off unless asked for: keeping someone's screen awake is a side
    # effect on their machine, not a default.
    ambient: bool = False


class FilterOption(BaseModel):
    """One Explore filter: a canonical facet, and how many artworks are behind it."""

    value: str
    """The facet key — `style.japanese`. Stable, and what a preference stores."""

    count: int
    """Constrained by whatever else is selected, so it is what choosing this would yield.
    Zero means the option is shown disabled rather than removed: a list that reshuffles
    under the cursor is worse than a greyed row."""

    label: str
    """Our English label. The frontend translates `facet_style_japanese` and falls back to
    this, so an untranslated facet degrades to English rather than to a slug."""


class FiltersResponse(BaseModel):
    """The filters worth offering, biggest first.

    Only options the local index can sustain appear here: a filter yielding four
    artworks is worse than no filter (docs/product-spec.md). The counts are real, from
    the index, not from a hardcoded list that would drift from what the API supports.

    Since M10 these are canonical facets rather than AIC's raw cataloguing, and the counts
    are *dependent*: each group is counted under the other groups' current selection, so
    choosing a style updates the subject and type counts without collapsing the style list
    the user is standing in.
    """

    museum: str = "aic"
    """Which source this vocabulary describes. A live source has one small list and no
    style, subject or exclusion at all, so the panel needs to know which shape it got."""

    artwork_types: list[FilterOption] = []

    styles: list[FilterOption] = []
    subjects: list[FilterOption] = []
    """Where artwork type is a closed vocabulary of 30-odd facets, these two run to
    hundreds, so they are also capped at the most populous few — `maximum_options`. A list
    nobody can scroll to the end of is not a filter either."""

    minimum_count: int
    maximum_options: int
    indexed_total: int


class ScoringWeight(BaseModel):
    """One curated signal and what it is worth, taken from the code rather than prose.

    `share` is the fraction of the total, which is the number a person can actually read:
    "3.0" means nothing without the other five, and "35%" means something on its own.
    """

    name: str
    weight: float
    share: float


class ScoringResponse(BaseModel):
    """How curated mode ranks, straight out of `domain.scoring.WEIGHTS`.

    An endpoint rather than a paragraph in the UI, so retuning a weight updates what the
    panel says instead of quietly making it wrong. The wording that goes with each `name`
    lives in `locales/`; only the numbers come from here.
    """

    weights: list[ScoringWeight]


class FeedbackItem(BaseModel):
    """One judged artwork, with enough of it to list and to show again."""

    museum: str = "aic"
    artwork_id: int
    kind: Literal["like", "dislike", "hide"]
    title: str | None = None
    artist: str | None = None
    image_id: str | None = None
    created_at: str


class FeedbackRequest(BaseModel):
    """A verdict, with the snapshot the display already has on screen.

    The snapshot travels with the request because the server may never have seen this
    artwork: it can have come from AIC live, from Cleveland or from the bundled set and
    not be in the index. See migration 009.

    `dislike` arrived with M13 and sits between the other two: a ranking signal that does
    not remove the artwork from the rotation. Migration 010.
    """

    kind: Literal["like", "dislike", "hide"]
    museum: Literal["aic", "cma"] = "aic"
    title: str | None = Field(default=None, max_length=500)
    artist: str | None = Field(default=None, max_length=300)
    image_id: str | None = Field(default=None, max_length=100)


class FeedbackSummary(BaseModel):
    """What the display needs to know about the personal mode without asking twice."""

    likes: int
    dislikes: int = 0
    hides: int
    personalising: bool
    """Whether there are enough likes for "For you" to mean anything. Below the threshold
    the mode falls back to curated ranking and the panel says so."""

    minimum_likes: int


class InterpretationResponse(BaseModel):
    """One AI interpretation, plus who produced it.

    The provider and model travel with the text because the display labels it as
    generated. Anything the model produces is presented as interpretation, never as fact
    (`docs/product-spec.md`), and naming the source is part of not pretending otherwise.
    """

    artwork_id: int
    language: Literal["en", "pl"]
    provider: str
    model: str

    visual_description: str
    interpretation: str
    themes: list[str]
    look_closer: str


class VisualDescriptionResponse(BaseModel):
    """One accessibility description, plus who produced it and from what.

    `grounded_in` names the museum field the description was built from, and it is on the
    response because the display says so out loud. A listener cannot check a description
    against the artwork, so the one thing they can be told is where the words came from:
    the Art Institute's own alt text, expanded — not a model looking at a picture.
    """

    artwork_id: int
    language: Literal["en", "pl"]
    provider: str
    model: str

    summary: str
    description: str
    grounded_in: Literal["alt_text", "description"]


class AiStatus(BaseModel):
    """What the frontend needs to know before offering the feature at all."""

    enabled: bool = False
    describes: bool = False
    """Whether the live provider can also write accessibility descriptions. Separate from
    `enabled` because it is a capability of the provider rather than of the deployment —
    Anthropic can, OpenAI does not yet, and the display offers the control accordingly."""

    provider: str | None = None
    model: str | None = None
    circuit_open: bool = False
    """True while the provider is being left alone after repeated failures. `enabled` still
    reports what is configured; this reports whether it is currently being called."""


class AiKeyRequest(BaseModel):
    """A key the user pasted into the settings panel.

    `SecretStr` rather than `str` so that the shape cannot print its own contents: this
    model is exactly the kind of thing that ends up in a traceback or a debugger.

    It does not, on its own, keep the key out of a rejection — pydantic reports the raw
    input it was given, before this field type applies. That is handled in
    `app/api/errors.py`, and a test here sends a malformed key and looks for it in the
    response body.
    """

    provider: Literal["anthropic", "openai"]
    """The vendors bring-your-own supports. `mock` is not one: it needs no key."""

    api_key: SecretStr = Field(min_length=8, max_length=512)

    @field_validator("api_key")
    @classmethod
    def _looks_like_a_key(cls, value: SecretStr) -> SecretStr:
        """Reject what cannot be an API key, and nothing more.

        No vendor prefixes are checked. They change, and a key rejected here for looking
        wrong would be indistinguishable to the user from a key the provider rejected —
        so the only rules are the ones that would break the HTTP request itself.
        """
        raw = value.get_secret_value()
        if raw != raw.strip():
            # Almost always a stray newline from a copy-paste, and stripping it silently
            # is the kinder answer than a validation error.
            raw = raw.strip()
        if not raw or any(character.isspace() for character in raw):
            raise ValueError("an API key cannot contain whitespace")
        if not raw.isascii() or not raw.isprintable():
            raise ValueError("an API key must be printable ASCII")
        return SecretStr(raw)


class AiKeyResponse(BaseModel):
    """The key situation, with no key in it.

    `key_hint` is the last four characters at most — `core/redaction.py` — and it is the
    only part of a key that ever crosses this boundary. `CLAUDE.md` makes that a
    non-negotiable, so the field is named for what it is.
    """

    enabled: bool
    provider: str | None = None
    model: str | None = None
    source: Literal["none", "environment", "keyring", "database"] = "none"
    key_hint: str = ""
    storage: Literal["keyring", "database"] = "database"
    """Where a key saved from here would go. `database` means unencrypted, and the panel
    says so before anything is typed."""


class CacheStats(BaseModel):
    """How often an interpretation was already on hand.

    The number that says whether the cache is doing its job. A low ratio on a display
    nobody presses `I` twice on is expected; a low ratio on one artwork asked about
    repeatedly means the cache key is changing when it should not.
    """

    hits: int = 0
    misses: int = 0
    hit_ratio: float = 0.0


class ProviderStats(BaseModel):
    """What the AI provider has cost in time and reliability, since this process started."""

    name: str | None = None
    model: str | None = None
    calls: int = 0
    errors: int = 0
    error_rate: float = 0.0
    average_ms: float = 0.0
    max_ms: float = 0.0
    circuit_open: bool = False


class AicStats(BaseModel):
    """Requests to the museum, and how many did not come back.

    Counted per call made by the app, not per HTTP attempt: the client's own retries are
    its business. A 404 counts as an error, because on this app it usually means the local
    index has gone stale against a record AIC has withdrawn.
    """

    requests: int = 0
    errors: int = 0
    error_rate: float = 0.0


class UsageStats(BaseModel):
    """Today's AI spend, per provider, read from `ai_usage`.

    The only part of /api/stats that survives a restart, because it is the only part the
    budget guard enforces against.
    """

    day: str
    providers: dict[str, dict[str, int]] = {}


class StatsResponse(BaseModel):
    """Operational numbers. Not a dashboard, and not persisted — see `domain/metrics.py`.

    Everything but `usage` counts from process start and is gone on restart. That is the
    scope these questions are asked at: is the cache working, is the provider slow, is AIC
    flaking, right now, on the display in front of me.
    """

    uptime_seconds: float
    indexed_artworks: int
    interpretation_cache: CacheStats = CacheStats()
    provider: ProviderStats = ProviderStats()
    aic: AicStats = AicStats()
    usage: UsageStats


class HealthResponse(BaseModel):
    status: str = "ok"
    ai: AiStatus = AiStatus()
