# 0007. Public-domain artworks only

Status: Accepted
Date: 2026-09-02

## Context

AIC's IIIF service will serve images for works that are not in the public domain, and the
documentation states plainly that determining whether such use is permitted, and obtaining any
necessary permission, is the caller's responsibility.

The API exposes `is_public_domain` as a filterable field, and AIC's own developer guidance
recommends using only works tagged that way.

## Decision

Filter to `is_public_domain == true` at index time and again at display time. It is a hard
constraint in `CLAUDE.md`, not a scoring preference.

## Alternatives considered

**Show everything, prefer public domain.** Leaves rights determination to runtime and, for an
application whose entire purpose is displaying images continuously, that is the wrong place for
an unresolved question.

**Case-by-case rights handling.** Requires rights metadata the API does not provide.

## Consequences

A smaller corpus, skewed towards older work — which suits an ambient display anyway. It also
unlocks the `1686` IIIF width, which AIC offers for public-domain works specifically.

The `description` field carries a CC BY 4.0 licence separate from the CC0 covering other data,
so the overlay attributes the Art Institute of Chicago whenever a description is shown.
