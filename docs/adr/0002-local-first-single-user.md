# 0002. Local-first, single user

Status: Accepted
Date: 2026-09-02

## Context

The original specification described both a locally-run desktop-style application and a hosted
service with bring-your-own API keys and a shared multi-user cache. Those are different products
with different obligations, and several downstream decisions cannot be made until this one is.

Accepting third-party API keys over the network makes us responsible for their storage and
handling. A hosted deployment needs abuse prevention, per-user rate limiting, and key isolation.
None of that serves the actual goal, which is a good-looking ambient display on a second monitor.

## Decision

vitrine is local-first. It runs on the user's own machine, binds to localhost, and serves a
single user. Any API key it holds is the operator's own.

## Alternatives considered

**Hosted, multi-tenant.** Would justify the shared cache and make the project a more conventional
web service. It also multiplies the security surface and the operational work for no gain in the
experience, and it is the version far more likely to be abandoned half-built.

**Both, behind configuration.** Every security decision would have to be made for the strictest
case anyway, so this is the hosted option with extra branching.

## Consequences

Bring-your-own keys become tractable: the key never crosses a network we do not control, and
storing it locally is a documented trade-off rather than a liability. Rate limiting and abuse
prevention drop out of scope. The shared cache loses most of its rationale (ADR-0004).

We revisit this if the app is ever to be deployed for other people, which would require
reopening key storage, cache writes, and request limits together.
