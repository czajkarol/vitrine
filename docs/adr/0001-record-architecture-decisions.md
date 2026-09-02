# 0001. Record architecture decisions

Status: Accepted
Date: 2026-09-02

## Context

This project is built largely by an autonomous coding agent, with the human acting as reviewer
and product owner. That creates a specific risk for a portfolio project: the code may be good
while the reasoning behind it is invisible, and reasoning is what a reader is actually assessing.

Commit messages carry the "what". Nothing currently carries the "why".

## Decision

Record significant architectural decisions as numbered ADRs in `docs/adr/`. Write one when a
decision forecloses an alternative a reasonable engineer would have chosen. The agent proposes
ADRs; the human accepts them.

## Alternatives considered

**A design document.** Goes stale as a whole, and there is no natural moment to update it.
ADRs are append-only and each one is finished when written.

**Comments in code.** Right place for local "why", wrong place for decisions spanning modules.

**Nothing.** Cheapest, and leaves the most interesting part of the project undocumented.

## Consequences

Small ongoing cost per decision. In exchange, the repository carries an explicit trail of
judgement, which is the part of an agent-assisted project that is otherwise hardest to see.
