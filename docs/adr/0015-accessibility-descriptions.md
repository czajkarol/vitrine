# 0015. Accessibility descriptions grounded in the museum's alt text, not in the image

Status: Accepted
Date: 2026-09-04

## Context

The owner asked for an accessibility feature built on the existing AI system:

> Generate a concrete visual description intended to help someone visualize the artwork.
> Anthropic only for now. Add TTS playback. Allow replaying an already generated description
> without regenerating it. Make the result usable with keyboard/screen readers where practical.
> Check and document realistic AI + TTS costs. When this feature is used, keep the next rotation
> interval at ≥5 minutes.

The request contains a trap, and it is worth naming before the decision. "A concrete visual
description" is exactly the output a language model will produce whether or not it has anything
to produce it from. Given a title, a date and a medium, a model will write a fluent, specific,
plausible description of an artwork that does not exist. And the reader — the entire point of
the feature — is the one person who cannot check it against the screen.

Everywhere else in this app a wrong AI sentence is recoverable: `docs/product-spec.md` requires
generated text to be labelled and visually separated, and a sighted user reading a bad
interpretation can see the painting disagreeing with it. That safety net does not exist here.

What makes the feature possible is a field that was already load-bearing:
`thumbnail.alt_text` is written by a person at the Art Institute who looked at the artwork, and
**all 57,607 indexed works have one.** They average about 65 characters — "Engraving of an old
man seated on the floor of a modest room, nude but for a cloth draped around his shoulder and
hip, hand on his heart…" is a long one; many are a single clause.

## Decision

**The description is an expansion and rearrangement of the museum's own words. No model sees the
image, and the display says so.**

Four parts, and the first is the one the rest exist to protect:

1. **Grounding is a precondition, checked before a call is made.** `domain/prompts.is_describable`
   requires `alt_text` or a `description`. An artwork with neither is refused with `422
   access_not_describable` — not a provider failure, and the display says something different
   about it. The check is before the call rather than after it because a listener cannot audit
   the answer, so the audit has to happen upstream of the money.
2. **The prompt's two strongest rules are about restraint.** Take everything visual from
   `alt_text` — or from `description` and `medium` where those describe appearance — and *match
   the length of your source*: a one-clause alt text should produce two or three sentences and
   stop. Padding a thin source is inventing, and a listener cannot tell the difference. The
   context sent is narrower than the interpretation's: `department` and `place_of_origin` are
   dropped, because they say nothing about what an artwork looks like and are precisely what a
   model reaches for when it has nothing else.
3. **The response says where the words came from, and the UI prints it.** `grounded_in` is
   `alt_text` or `description`, and the two read differently on screen — the museum describing
   the image, versus the museum describing the work. Both say "No AI has seen the artwork
   itself." This is not a disclaimer bolted on; it is the sentence that makes the feature honest,
   so it renders with the text rather than behind a fold.
4. **Speech is the browser's, not a vendor's.** `speechSynthesis`: no key, no per-word bill,
   works with the network down. Replay is a control rather than a second request, because the
   text is on screen and the server has it cached.

**Anthropic only is a capability, not a configuration flag.** `VisualDescriptionProvider` is a
second, `runtime_checkable` Protocol in `providers/ai/base.py`. Anthropic implements it; the mock
implements it, so the whole path is testable with no key; OpenAI does not. `/api/health` reports
`ai.describes` and the control is not offered when it is false. A vendor name compared above
`providers/` is forbidden by `CLAUDE.md`, and a method on the shared Protocol would have made
OpenAI implement it by raising — a capability a provider "has" and refuses is worse than one it
visibly lacks. Making OpenAI eligible later is adding one method, in one file, with no second
place to remember.

**Asking for a description puts a five-minute floor under the rotation, without changing the
saved interval.** A spoken description takes most of a minute; at the 30-second rung the artwork
is gone before the end of it. A floor rather than an assignment, so the user's own choice comes
back when the floor lifts.

Both generated kinds share one provider, one daily budget, one circuit breaker, one timeout and
one cache — keyed by `kind`, appended to the key string only when it is not the default, so no
interpretation cached before this was invalidated. Two budgets would have been two numbers to
reason about and one of them silently spent.

## Alternatives considered

**Send the image to a vision model and describe what it actually shows.** This is the honest
version of the feature, and it is the one to revisit first. It was not built for three reasons,
in order of weight. It changes the provider contract from "text in, text out" to "image in",
which `InterpretationRequest` and both existing providers are not shaped for. It costs
meaningfully more per call — an 843px image is on the order of a thousand input tokens on its
own, before the prompt. And it removes the one thing that currently makes the output checkable:
today, every sentence traces to a field a sighted person can read, which is what lets the
display make a specific claim about provenance instead of a vague one. A vision description
would be better *and* would need a different, weaker honesty claim. **What would make us
revisit:** somebody using this in earnest and finding the 65-character alt texts too thin, which
is the most likely outcome and the reason this paragraph is here.

**Reuse the interpretation's `visual_description` field.** It already exists and is already
grounded in `alt_text`. Rejected: it is one to three sentences written for someone *looking at*
the artwork, sitting inside a block whose next paragraph is explicitly speculative. Handing that
to a speech synthesiser would read hedged interpretation aloud as though it were description.

**A cloud TTS voice.** Better voices, particularly for Polish. Rejected on structure more than
on price: cloud TTS bills per character *per playback*, where the model call bills once and is
then cached — so replay, which the owner asked for by name, would be the expensive operation.
At neural-tier rates (roughly $15–20 per million characters) a ~750-character description is
about 1–1.5¢ each time it is played, against ~0.4¢ to write it. It would also need a key, a
network, and audio bytes crossing the machine, all for a feature whose value is that somebody
can rely on it. `docs/ai-system.md` carries the full arithmetic.

**Generate on rotation so it is ready when asked for.** Rejected for the same reason
`docs/ai-system.md` already rejects it for interpretation: most artworks are shown and never
asked about, and this is the single decision worth an order of magnitude of the AI bill.

**Its own daily budget.** Rejected — see above.

## Consequences

- **Almost nothing is refused in practice.** Every indexed artwork has `alt_text`, so
  `is_describable` bites only on the tiers that are not the index: a live AIC record, the bundled
  set, and Cleveland — which has no `alt_text` field at all and is excluded from the AI path
  entirely ([ADR-0013](0013-cleveland-as-a-live-source.md)).
- **The quality of the feature is the quality of AIC's alt text**, and that varies from a clause
  to a paragraph. The "match the length of your source" rule means a thin source produces a short
  description rather than a padded one, which is the correct failure and will sometimes be
  disappointing.
- **`VISUAL_PROMPT_VERSION` is versioned separately from `PROMPT_VERSION`.** Retuning the
  interpretation must not discard every description — the more expensive of the two to
  regenerate, and the one a returning listener is most likely to want again.
- **The `interpretations` table holds two kinds.** Migration 011 adds `kind` as a column as well
  as a key part, for the same reason `prompt_version` is one: retiring a kind wholesale should
  not be string surgery on a primary key.
- **The rotation floor is session-scoped and not persisted.** It is a consequence of what the
  user is doing right now, not a preference they set, and a display that had quietly slowed
  itself down permanently would be a setting nobody could find to undo.
- **Nobody has run this against a real key.** The mock proves the wiring and nothing about what
  Anthropic actually returns for this prompt — including whether the restraint rules hold on a
  one-clause alt text, which is the assumption the whole record rests on. That is the first
  thing to check when `pytest -m live` is finally run.
