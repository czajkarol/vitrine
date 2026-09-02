# 0004. Defer the shared cache to an interface

Status: Accepted
Date: 2026-09-02

## Context

The original specification described a shared public cache of AI interpretations, so that one
user's generated text could serve another, backed by a managed PostgreSQL service.

Under ADR-0002 this application has one user, so there is nobody to share with. Building the
service anyway would mean writes, validation, rate limiting, and abuse prevention for a database
with a single writer.

The proposed design also stored one canonical interpretation per artwork, language, and prompt
version, with the generating provider kept only as metadata. That means whichever installation
generated an entry first fixes its quality for everyone, with no path to improvement — a design
flaw worth catching now rather than after it is built.

## Decision

Define `InterpretationCache` and implement it twice: `SqliteCache`, which is real, and
`NullSharedCache`, which always misses. The three-tier resolution chain — local, then shared,
then provider — is written as real code and covered by tests. No shared cache is deployed.

## Alternatives considered

**Build it.** Weeks of work on infrastructure for a single-user application, and it contradicts
this project's own stated preference against speculative infrastructure.

**Leave it out entirely.** Cheaper still, but enabling it later would then mean threading a new
tier through the interpretation service rather than swapping one class.

## Consequences

Enabling a shared cache later is a config flag and one new implementation. The chain costs a
handful of lines and one test. Nothing is deployed, nothing is operated, nothing can leak.

If this is revisited, the canonical-entry design needs rethinking first: entries should record
which provider and model produced them and allow a better-quality entry to supersede a worse one.
