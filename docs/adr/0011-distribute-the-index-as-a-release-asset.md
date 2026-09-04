# 0011. Distribute the index as a release asset, never in Git

Status: Accepted
Date: 2026-09-04

## Context

ADR-0003 put the artwork corpus in a local SQLite file because AIC's search endpoint caps
at 1,000 records and the collection is 132,741. The consequence nobody had to face until
now is what a *second* person does. Building the index means `scripts/build_index.py`
walking 1,328 pages at one request per second: 30 minutes, and traffic to somebody else's
service that `CLAUDE.md` requires the owner's approval for. That is a poor first
five minutes with the app, and it is 1,328 requests AIC did not need to serve twice.

The obvious fix is to ship the file. Three facts decide how.

**The database holds a secret.** When there is no OS keyring, a pasted API key is stored
unencrypted in `credentials`, in the same file as the index (ADR-0002's postscript,
migration 006). `data/vitrine.db` is therefore not a publishable artefact and never will
be, whatever else changes.

**The corpus itself is publishable.** It is AIC metadata for public-domain works and no
image bytes. AIC's collection data is CC0; the `description` field is CC BY 4.0 and
requires attribution, which the app already shows whenever a description is on screen
(`docs/aic-api.md`, ADR-0007).

**It is large and it is derived.** A full export is 58MB — `lqip`, the base64 blur
placeholders, are 15MB of that on their own — and it is rewritten whenever the crawl or
the scoring changes. The repository is 3MB.

## Decision

**The corpus is published as a GitHub Release asset. The database is never committed.**

- `scripts/export_index.py` writes `dist/vitrine-index.sqlite`: `artwork_index`,
  `artwork_terms`, `artwork_facets`, and `schema_migrations` so the file can say which
  schema it was built against. `VACUUM`ed, and in the default rollback journal mode rather
  than WAL, because a WAL database copied without its `-wal` sidecar is one missing its
  most recent writes.
- **The export is built by copying an allow-list of tables into a fresh file, never by
  deleting from a copy of the live one.** This is the safety property and it is the reason
  the code is shaped the way it is: a table added to the schema next year is absent from
  the export by default rather than present in it by default, and the table it might have
  sat next to holds an API key. `app/repositories/corpus.py` asserts the result rather than
  trusting the loop, and a test greps the finished file for a key that was in the source.
- `scripts/fetch_index.py` merges an export into `data/vitrine.db` by `ATTACH` and
  `INSERT OR REPLACE`, writing only the corpus tables. Preferences, history, favourites,
  cached interpretations and credentials are untouched: **fetching an index is not a
  factory reset.**
- A download is checked before it is opened and opened before it is merged — HTTPS only,
  a declared `Content-Length` within plausible bounds, and then the file itself read to
  confirm it is SQLite with exactly an export's tables. `--sha256` verifies it is *the*
  file rather than merely a well-formed one.
- The export carries scores. A fetched index must not need a local scoring pass before
  Curated, which is the mode the app leads with, has anything to serve.
- `data/` and `dist/` both stay gitignored.

## Alternatives considered

**Commit the database.** Simplest possible fetch: `git clone`. Rejected on all three facts
above — Git stores each 58MB rebuild in full and forever, a derived cache with a staleness
policy is not a source artefact, and the file contains a secret.

**Git LFS.** Solves the repository-size half. Rejected: it adds a tool, a bandwidth quota,
and a checkout that fails in a new way, all for a file that one command regenerates and
that a release asset serves without any of it.

**Ship the corpus as compressed JSON or CSV and import it.** Smaller on the wire and
diffable. Rejected because it needs an importer that reconstructs three tables and their
indexes, which is a second, subtly different write path beside the crawl's — and the
derived tables are exactly where a bug would be invisible until a settings panel showed
the wrong counts. SQLite in, SQLite out, and `ATTACH` does the work.

**Delete the private tables from a copy of the live database.** Fewer moving parts than
building a fresh file. Rejected, and this is the decision inside the decision: a deny-list
is wrong by default the moment somebody adds a table, and one of the tables it would have
to remember is the one with the key in it.

**Let `fetch_index.py` crawl AIC directly when there is no published export.** Rejected as
a silent way around the standing rule on sustained external traffic. If there is no export,
the answer is `build_index.py` and the approval it requires.

## Consequences

- **A published export must be re-cut whenever the corpus changes**, and there is nothing
  automatic about that. An export names its migrations, so a stale one merged into a newer
  checkout is refused rather than half-applied — but a *newer* export merged into an older
  checkout is the case that is caught, and a stale export merged into a matching checkout
  just quietly gives somebody an older corpus. The release notes carry the walk date.
- **58MB is bigger than the plan expected** (25–35MB was the estimate). `lqip` is the
  reason and it stays: it is what makes the crossfade start before the image arrives.
  Dropping it would save 15MB and cost the transition on every rotation.
- **The owner is publishing AIC's data.** The attribution requirement travels with the
  `description` field, which the app satisfies on screen; a release that includes the
  export should say the same thing in its notes.
- **Nothing verifies the publisher.** `--sha256` proves the file matches a digest, and the
  digest comes from the same release page as the file. That is enough against a corrupted
  download and nothing against a compromised repository. Signing was not built because the
  threat model here is ADR-0002's: one person, one machine, their own data.
- **What would make us revisit this:** a second art source (ADR-0012) makes "the corpus" a
  per-source thing, and the export would need to say which sources it carries rather than
  assuming one.
