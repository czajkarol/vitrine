# AI system

Optional throughout. The app is complete without it. Build it last — see `docs/roadmap.md`.

Claude Code is the development agent for this repository. It is not the runtime AI service.
Runtime interpretation goes through ordinary provider HTTP APIs.

---

## What the AI produces

A fixed, validated structure — not free text. This matters: the validated object is what gets
cached, and shapeless cache values make prompt versioning unmanageable.

```python
class Interpretation(BaseModel):
    visual_description: str      # what is literally visible
    interpretation: str          # what it might mean — hedged language
    themes: list[str]            # 2-5 short phrases
    look_closer: str             # one detail worth noticing
    language: Literal["en", "pl"]
```

The provider is instructed to return JSON matching this and nothing else. Parse, validate,
reject on failure. A rejected response is a cache miss, not an error shown to the user, and
"provider returned unparseable JSON" is a test case, not a surprise in production.

### The second kind: an accessibility description

M14 added a second thing the AI produces, for a different reader. See ADR-0015.

```python
class VisualDescription(BaseModel):
    summary: str                 # one sentence: what the artwork is
    description: str             # 3-8 sentences, read aloud
    language: Literal["en", "pl"]
```

**No model sees the image.** Everything visual comes from `thumbnail.alt_text` — written by a
person at the Art Institute who did look at the artwork, and present on all 57,607 indexed
works — plus `description` and `medium` where those describe appearance. The prompt's second
strongest rule is *match the length of your source*: a one-clause alt text should produce two or
three sentences and stop, because padding a thin source is inventing and the reader is the one
person who cannot tell the difference.

An artwork with neither alt text nor a description is refused before a call is made
(`is_describable`, HTTP 422 `access_not_describable`). The audit has to happen upstream of the
money, because it cannot happen downstream of it.

The response carries `grounded_in`, and the display prints which museum field the words came
from and that no AI has seen the artwork. That line is not a disclaimer bolted on — it is what
makes the feature honest, so it renders with the text rather than behind a fold.

### Prompt construction

Separate the instruction from the data. Museum metadata goes in as clearly delimited *content*,
never interpolated into the instruction text. AIC data is trustworthy, so this is hygiene rather
than active defence, but the structure should be right from the start.

Ground the prompt in `thumbnail.alt_text` where available — it is a human-written description of
the actual image, and it is the difference between the model describing this painting and the
model describing a plausible painting with this title.

Instruct explicitly: hedge interpretive claims, never assert biographical or historical facts not
present in the supplied metadata, and answer in the requested language.

---

## Prompt versioning

`PROMPT_VERSION` is a constant in the prompts module and part of every cache key. Bump it when
the prompt changes in a way that would change the output meaningfully. Do not bump it for a typo
fix — that just throws away a cache for nothing. Keep a short changelog in the prompts module
saying what changed at each version.

`VISUAL_PROMPT_VERSION` is a second constant, versioned independently. Retuning the
interpretation must not discard every accessibility description: those are the more expensive of
the two to regenerate and the ones a returning listener is most likely to want again.

---

## Cache

Key: `artwork_id | language | provider | model | prompt_version`, plus `| kind` for
anything that is not an interpretation — see below.

Resolution order:

```
local SQLite  →  shared cache (if enabled)  →  provider  →  write back to both
```

The shared cache is `NullSharedCache` and returns nothing. The chain is real code so that
enabling a shared cache later is a config change and one new class, not a redesign. It is not
implemented and should not be. See ADR-0004.

If a cache lookup raises, log it and fall through to the next tier. A corrupt cache must never
take the app down.

Since M14 the cache holds two kinds, distinguished by `kind` on the `CacheKey`
(`"interpretation"` or `"visual"`). It joins the key string **only when it is not the default**,
so every interpretation cached before M14 kept the key it was written under — adding a field to
a cache key is otherwise a silent, total invalidation. Migration 011 also adds `kind` as a
column, for the same reason `prompt_version` is one: retiring a kind wholesale is a bulk
operation and doing it by string surgery on a primary key is how you delete the wrong rows.

---

## Providers

```
providers/ai/
    base.py       the Protocol, the errors, and parse_interpretation()
    http.py       the POST, the timeout and the error map both real providers share
    mock.py       deterministic, used by the entire test suite
    factory.py    the only place a configured name becomes a class
    anthropic.py  built first; also implements VisualDescriptionProvider
    openai.py     built second, to test the abstraction
    gemini.py     not built
```

Build `base.py` and `mock.py` first, wire the whole feature end to end against the mock, and
only then add one real provider. Adding the second real provider is what proves the abstraction
holds — if it requires changing `base.py`, the abstraction was wrong and now is the time to know.

**Outcome, recorded because it was the point of the exercise.** OpenAI arrived second and
`base.py` did not change. The two vendors disagree about nearly everything on the wire — the
system prompt is a field at Anthropic and a message at OpenAI; the output cap is `max_tokens`
against `max_completion_tokens`; token counts come back as `input_tokens`/`output_tokens`
against `prompt_tokens`/`completion_tokens`; JSON is an instruction at one and a request
parameter at the other — and all of it stayed inside the two provider modules.

What the second provider *did* change was `http.py`, which did not exist before it: both were
about to duplicate a client, a POST, an error map and a redaction rule. That is shared
implementation, not a shared interface, so it sits beside the providers rather than in
`base.py`. A provider that needs a different transport — a vendor SDK, a streaming socket —
implements the Protocol without it and nothing else has to know.

No test in the default suite may hit a paid API. Real providers are exercised only under
`-m live`, which is excluded from CI.

### Capabilities, not configuration flags

Not every provider does everything, and M14 made that structural rather than conditional.
`VisualDescriptionProvider` is a second, `runtime_checkable` Protocol beside
`InterpretationProvider`. Anthropic implements it; `MockProvider` implements it, so the whole
accessibility path is testable with no key and no network; OpenAI does not.

The alternatives were both worse. A vendor name compared above `providers/` is forbidden outright
by `CLAUDE.md`. A `describe()` method on the shared Protocol would have forced OpenAI to
implement it by raising, and a capability a provider claims and then refuses is worse than one it
visibly lacks. `/api/health` reports `ai.describes`, and the display does not offer a control
that would refuse.

Making OpenAI eligible later is adding one method in one file. There is no second place to
remember.

### Two configuration modes

**Configured provider** — `AI_PROVIDER` and the matching key in `.env`, read at startup.

**Bring your own** — the user pastes their own key in settings. Because this app is local-first
(ADR-0002), storing it in the local SQLite file is acceptable, but it must be documented plainly
in the README: the key is stored unencrypted on your machine, in a file you control. Prefer the
OS keyring if `keyring` is available and fall back to SQLite with that warning shown in the UI.

Never log a key. Never return one from an API endpoint. Redact to last four characters everywhere.

**And say all of that in the panel, in words somebody non-technical can read.** The panel used
to answer half the question -- it named the store ("keyring") without saying what one is, and
said nothing at all about what happens to the key on the way there. It now states the four
things that are true and stops: the key is sent from vitrine to the provider rather than from
the page, it never reaches a log, everywhere else it appears it is its last four characters,
and it is kept either in the OS password store or unencrypted in `data/vitrine.db`. The second
half of that last one is a warning and reads as one. Nothing there is reassurance beyond what
this section can back up. M17.

**Collapsed since M18, and the summary carries the fact rather than a label.** Two paragraphs
of it in front of somebody every time they open the panel is more than most people want, so
the long form is behind a disclosure — but a disclosure summary reading "where your key is
kept" would put the required warning one click *away* from the person who has to act on it.
So the summary is the one-line answer for this machine, written from `/api/ai/key`: "kept in
your computer's own password store", or "kept unencrypted in vitrine's own file", the second
of which is set apart from the panel's other asides. What this section requires the UI to say
is therefore still said without opening anything; what is behind the triangle is why, and what
to do about it.

**How it came out.** `repositories/credentials.py` holds both backends and picks between them
once, at startup, rather than per call — a key written to the keyring and then looked for in
SQLite would read as "no key" and quietly turn the feature off. The choice is a probe, not an
import check: `import keyring` succeeds on a machine with no working credential store, and the
backend it resolves to raises only when you use it. So the store reads a name nothing is ever
stored under, and falls back to SQLite if that throws.

`services/ai_credentials.py` is the seam between the two modes. It swaps the live provider
without a restart — a user who has just typed a key and been told to restart the server has been
told the feature does not work — and resets the circuit breaker as it does, because a failure
count belongs to the provider that earned it. A saved key outranks `.env`: it is the later and
more deliberate of the two. `AI_ENABLED` is not consulted for it, because pasting a key *is* the
decision to enable the feature.

Everything about a missing or unreadable key degrades to "AI is off", never to a failed boot.
The keyring being cleared behind the app's back is an ordinary Tuesday.

**One thing redaction did not cover, found by a test.** `PUT /api/ai/key` takes the key in a
request body, and FastAPI's own 422 echoes the offending input back to the caller — so a key
with a stray character in it came straight back out in the error, `SecretStr` or not, because
pydantic reports what it was given before the field type applies. `app/api/errors.py` drops
`input` and `ctx` from every validation error for that reason. Nothing about the original code
read as a leak; the only way it was going to be found was a test that sent a malformed key and
looked for it in the response.

---

## Budget and failure control

Cost control is a feature, not an afterthought. Without it, a rotation set to one minute with
AI enabled will make 1,440 API calls a day.

- Hard cap on output tokens per request.
- Daily request cap, tracked in `ai_usage`, enforced before the call is made.
- Circuit breaker: after N consecutive provider failures, open for a cooling period and answer
  from cache only. Log the transition, surface it on `/api/health`.
- Per-request timeout, short. If the interpretation is not ready before the artwork rotates
  away, cancel it.
- Never generate on rotation. Generate on demand — when the user actually opens the overlay.
  This one decision cuts AI cost by an order of magnitude, because most artworks are never
  asked about.

---

## What it actually costs

Measured on 2026-09-04 against 300 randomly sampled indexed artworks, by building the real
prompts with `build_prompt` and `build_visual_prompt` and counting characters.

**These are estimates, and the estimate is stated so it can be replaced.** Token counts are
derived from characters at roughly 3.6 chars/token, which is the usual ratio for English prose
with punctuation and embedded JSON. Nobody has run `client.messages.count_tokens` against these
prompts, because nobody has run this app with a real key at all — see the outstanding items in
`HANDOFF.md`. Confirming these numbers is one call and should happen the first time a key exists.

| | System instruction | Median prompt | p90 prompt | Approx. input tokens (median / p90) |
|---|---|---|---|---|
| Interpretation | 1,411 ch | 1,734 ch | 2,085 ch | ~480 / ~580 |
| Visual description | 1,962 ch | 2,214 ch | 2,555 ch | ~615 / ~710 |

Output is capped at `AI_MAX_OUTPUT_TOKENS` (600). A realistic interpretation is 250-350 tokens
across its four fields; a realistic description is 150-350.

At `claude-sonnet-5`, the default model in `providers/ai/anthropic.py` ($2.00 / $10.00 per
million tokens in / out):

| | Typical | At the output cap |
|---|---|---|
| One interpretation | ~$0.0040 | ~$0.0072 |
| One visual description | ~$0.0037 | ~$0.0074 |

So **under half a cent each**, and the two are within a rounding error of one another — the
description's longer prompt is offset by its shorter answer.

**The daily ceiling.** `AI_DAILY_REQUEST_LIMIT` defaults to 200, and since M14 the two kinds
share it. Fully spent, every day:

| | Per day | Per 30 days |
|---|---|---|
| 200 requests, typical | ~$0.75 | ~$22 |
| 200 requests, at the cap | ~$1.48 | ~$45 |

That is the worst case for a budget nothing has ever come close to spending, because generation
is on demand: most artworks are shown and never asked about. `claude-haiku-4-5` ($1.00 / $5.00)
halves it again if the ceiling ever becomes real.

### Text to speech costs nothing, and that is a structural choice

Playback is the browser's own `speechSynthesis` (`frontend/js/speech.js`). No key, no network,
no per-word charge, and it works with both museums unreachable — which matters more here than
voice quality does, because the point of the feature is that somebody can rely on it.

A cloud neural voice would sound better, particularly in Polish. It was rejected on **structure**
rather than on price: cloud TTS bills per character *per playback*, where the model call bills
once and is then cached. Replay — which the owner asked for by name — would be the expensive
operation.

At neural-tier rates, which the major providers publish in the region of $15-20 per million
characters, a ~750-character description is roughly **1-1.5¢ every time it is played**, against
~0.4¢ once to write it. Ask for a description and listen to it three times and the speech has
cost an order of magnitude more than the intelligence did. The exact rate does not change the
shape of that argument.

Two `speechSynthesis` traps are handled in `speech.js` and are worth knowing about: voices load
asynchronously and `getVoices()` returns `[]` on first call in Chrome, so the list is primed at
boot; and a long utterance is truncated in some builds, so the text is split at sentence
boundaries — which also makes `cancel()` take effect at the next boundary rather than after the
whole thing.

### The one cost control that is not a number

Generation stays on demand — `I` for an interpretation, `A` for a description. This is still the
single decision worth an order of magnitude, and it now applies to two features rather than one.

Asking for a description also puts a five-minute floor under the rotation. That is not a cost
control, but it interacts with one: at the 30-second rung an unattended display with generation
on rotation would be the 2,880-calls-a-day scenario this section exists to prevent.

---

## Streaming

Interpretation is the one slow thing in the app. Stream it over SSE so text appears progressively
rather than the panel sitting empty. Cancel the stream when the artwork changes or the overlay
closes — an abandoned generation still costs money.

Do this after the non-streaming path works and is cached. It is a refinement, not a foundation.

---

## Presentation rules

AI output is always labelled and always visually separated from museum data. Anything the model
produces is presented as interpretation, never as fact. If the provider is unavailable or the
budget is spent, the overlay shows museum data alone with a quiet note — never an error dialog.
