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

---

## Cache

Key: `artwork_id | language | provider | model | prompt_version`

Resolution order:

```
local SQLite  →  shared cache (if enabled)  →  provider  →  write back to both
```

The shared cache is `NullSharedCache` and returns nothing. The chain is real code so that
enabling a shared cache later is a config change and one new class, not a redesign. It is not
implemented and should not be. See ADR-0004.

If a cache lookup raises, log it and fall through to the next tier. A corrupt cache must never
take the app down.

---

## Providers

```
providers/ai/
    base.py       the Protocol, the errors, and parse_interpretation()
    http.py       the POST, the timeout and the error map both real providers share
    mock.py       deterministic, used by the entire test suite
    factory.py    the only place a configured name becomes a class
    anthropic.py  built first
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

### Two configuration modes

**Configured provider** — `AI_PROVIDER` and the matching key in `.env`, read at startup.

**Bring your own** — the user pastes their own key in settings. Because this app is local-first
(ADR-0002), storing it in the local SQLite file is acceptable, but it must be documented plainly
in the README: the key is stored unencrypted on your machine, in a file you control. Prefer the
OS keyring if `keyring` is available and fall back to SQLite with that warning shown in the UI.

Never log a key. Never return one from an API endpoint. Redact to last four characters everywhere.

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
