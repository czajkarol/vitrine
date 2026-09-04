# Data

What vitrine stores, what it can rebuild, what may be published, and what must not be.

Everything lives in one SQLite file, `data/vitrine.db` by default (`DATABASE_PATH`). It is
gitignored, and [ADR-0011](adr/0011-distribute-the-index-as-a-release-asset.md) is why that
is not going to change.

---

## The short version

**Never commit, publish, or attach `data/vitrine.db`.** When there is no OS keyring, it
holds an API key in plain text. Publish `dist/vitrine-index.sqlite` — the output of
`scripts/export_index.py`, which is built from an allow-list and cannot carry one.

---

## What is in it

| Table | Kind | Holds | If you lost it |
|---|---|---|---|
| `artwork_index` | Rebuildable corpus | One row per indexed public-domain artwork: AIC's metadata, the blur placeholder, the curated score | Re-run the walk (~30 min) or fetch a published export |
| `artwork_terms` | Rebuildable corpus | AIC's own style and subject values, verbatim | Same |
| `artwork_facets` | Derived | The canonical facets every filter queries ([ADR-0009](adr/0009-canonical-facets.md)) | `build_index.py --retag`, no network, ~2s |
| `interpretations` | Cache | AI-written interpretations, keyed by artwork, language, provider, model and prompt version | Costs money to regenerate; nothing breaks |
| `ai_usage` | Counters | Requests and tokens per day per provider | Today's spend cap resets; nothing breaks |
| `preferences` | User state | Mode, interval, language, filters, the remembered IIIF base | Mildly annoying |
| `history` | User state | The last ~50 artwork ids, for the repeat penalty | Mildly annoying |
| `artwork_feedback` | **User data** | Likes and hides, with a title/artist/image snapshot ([ADR-0010](adr/0010-personalisation-from-explicit-feedback.md)) | Your favourites, and "For you" goes back to cold |
| `credentials` | **A secret** | A pasted API key, unencrypted, when no OS keyring is available | Your API key |
| `schema_migrations` | Bookkeeping | Which migrations have run | Migrations would re-run and fail |

`data/vitrine.db-wal` and `data/vitrine.db-shm` sitting beside it are normal: the database
runs in write-ahead-logging mode so `build_index.py` can write while the display reads.
They are part of the database, not leftovers — copy a WAL database without them and you
have copied it without its most recent writes.

## Where a key actually ends up

`app/repositories/credentials.py` prefers the OS keyring and falls back to the `credentials`
table. The settings panel says which one it got, before anything is typed, because the two
have genuinely different consequences:

- **Keyring available** — the key is in the OS credential store. `data/vitrine.db` holds no
  secret. This is the ordinary case on a desktop.
- **No usable keyring** — the key is a row in `credentials`, in plain text, in the same file
  as the index. An installed `keyring` package with no working backend counts as no keyring:
  it raises only when used, so it is probed rather than trusted.

Either way the key never leaves the machine and is never sent to the frontend
(`CLAUDE.md`), and it is redacted to its last four characters in every log line and error
response.

## Is the corpus publishable? Yes, with attribution

The index holds AIC metadata for public-domain works and **no image bytes**. AIC's
collection data is CC0. The `description` field is CC BY 4.0 and requires attribution,
which the app carries on screen whenever a description is shown
(`docs/aic-api.md`, [ADR-0007](adr/0007-public-domain-only.md)). A published export should
say the same thing in its release notes.

Only artworks with `is_public_domain == true` are ever indexed, so there is nothing else in
there to worry about.

## Publishing an export

```bash
uv run python scripts/export_index.py                  # → dist/vitrine-index.sqlite
uv run python scripts/export_index.py --force          # overwrite an existing one
```

It copies `artwork_index`, `artwork_terms`, `artwork_facets` and `schema_migrations` into a
**fresh** file and `VACUUM`s it. No network. Against the full corpus that is about a second
and a half, and the result is ~58MB for 57,607 artworks — `lqip`, the base64 blur
placeholders, are 15MB of that.

The allow-list is the safety property, and it is worth understanding rather than trusting.
The export is *built up* from named tables, never *cut down* from a copy of the live
database. A table added to the schema next year is therefore absent from an export by
default. `app/repositories/corpus.py` then asserts the finished file contains nothing else,
and `tests/test_corpus_transfer.py` greps it for a key that was present in the source.

Publish it as a GitHub Release asset with its `sha256`, and say in the notes when the walk
was done.

## Fetching one

```bash
uv run python scripts/fetch_index.py --url https://.../vitrine-index.sqlite --sha256 <digest>
uv run python scripts/fetch_index.py --file dist/vitrine-index.sqlite
uv run python scripts/fetch_index.py --file dist/vitrine-index.sqlite --dry-run
```

It writes **only** the corpus tables. Preferences, history, favourites, cached
interpretations and credentials survive: fetching an index is not a factory reset. Artworks
already present are refreshed in place, new ones are added, and running it twice changes
nothing the second time.

A download is checked before it is opened and opened before it is merged — HTTPS only, a
declared `Content-Length` within plausible bounds, and then the file itself read to confirm
it is SQLite with exactly an export's tables. Pointing it at your own `data/vitrine.db` by
mistake is refused, by name, because that file has tables an export does not.

An export names the migrations it was built against. One built by a newer checkout than
yours is refused rather than written into a schema that has not caught up.

## The index is a cache, not truth

[ADR-0003](adr/0003-local-artwork-index.md). AIC can unpublish or replace an image at any
time, and a row in `artwork_index` is a claim about what was true during the walk. The
display handles that at the point it matters: an image that will not load is skipped and
another artwork is shown. Nothing repairs the row, and nothing needs to.

So the corpus goes stale slowly and safely. Re-walking is how it is refreshed:

```bash
uv run python scripts/build_index.py               # the full walk — needs the owner's approval
uv run python scripts/build_index.py --score-only  # retune scoring, no network
uv run python scripts/build_index.py --retag       # rebuild the facets, no network
```

The full walk is 1,328 requests over about 30 minutes. It stays inside AIC's documented
limits and it still needs asking first, because the rule is about volume and duration
rather than permission — `CLAUDE.md`, `QUESTIONS.md` #8.

## Deleting it

Stop the server and delete `data/vitrine.db` along with its `-wal` and `-shm` files. The app
recreates and migrates an empty one on the next start, and serves from AIC and then from the
bundled 30-artwork fallback set until an index exists. You will lose your favourites and,
if there is no keyring, your API key.
