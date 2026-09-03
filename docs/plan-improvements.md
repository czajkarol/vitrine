# Improvement plan — M7 to M12

Written 2026-09-03, after reading the whole repository against `CLAUDE.md`, the roadmap, the
ADRs and the live index. `docs/roadmap.md` carries the tickable milestone list; this file
carries the design and the reasoning that is too long for it.

Everything below is agreed scope. Four shaping decisions were taken by the owner before this
was written and are recorded in "Decisions taken" at the end. Open questions are in
"Still needs a ruling".

---

## What is true right now

M0–M6 are all complete, **M3.5 included** — style and subject are indexed, filterable and in
the panel. The index holds 57,607 artworks, all scored, and 84,190 style/subject term rows in
`artwork_terms`. `data/vitrine.db` is 60MB and gitignored.

Several documents still say otherwise. Reconciling them is Phase 0 and is not optional: a fresh
agent reading `README.md` today is told style and subject filters are not built.

---

## Phase 0 — Truth-up. No behaviour change

Do this first and in one commit per group. It is cheap, and every later phase edits these files.

### 0.1 Neutral naming

`Karol` appears in `CLAUDE.md`, `HANDOFF.md`, `QUESTIONS.md`, `docs/roadmap.md`. Replace with
**"the owner"** — the role, which is what every one of those sentences actually means
("ask the owner before a full crawl"). Do not invent a persona.

A personal email address is also committed in three places and is not the same problem, but is
worth fixing while here:

- `app/core/config.py` — `aic_user_agent` defaults to `"vitrine (karolkczaj@gmail.com)"`.
  Change the default to `"vitrine (set AIC_USER_AGENT in .env)"` and log one WARNING at startup
  when it is still the default, because AIC asks for a real contact address on every request.
- `tests/conftest.py` — use `vitrine-tests (tests@example.invalid)`.
- `docs/aic-api.md` — the courtesy-header row shows the address; use the placeholder.

### 0.2 Documents that contradict the code

| File | What is wrong |
|---|---|
| `HANDOFF.md` | Says "every milestone complete except M3.5, which is parked" *and* "M3.5 is finished", four paragraphs apart. Says "the roadmap has one unticked section, M3.5" — it has none. Repeats the M5 live-key item twice. |
| `README.md` | Limitations claims "Style and subject filters are not built". The Settings and "Explore and Curated" paragraphs list artwork type only. |
| `README.md`, `HANDOFF.md` | Both say "334 tests". Count them and write the real number, or drop the number. |
| `docs/architecture.md` | Persistence block lists a `classification` column, renamed to `artwork_type` by migration 002. Omits `artwork_terms` and `credentials` entirely. Frontend tree omits `interpretation.js`. |
| `docs/roadmap.md` | M3.5 preamble still says "ask the owner before starting it" in the present tense for a walk that finished. |
| `pyproject.toml` | The `ai` extra installs `openai`, `anthropic` and `google-genai`. Nothing imports any of them — both providers are hand-rolled over `httpx` in `providers/ai/http.py`. Remove the extra, or reduce it to a comment saying why it is empty. |
| `.env.example` | `GEMINI_API_KEY` and `SHARED_CACHE_*` have no matching `Settings` fields. `extra="ignore"` hides it. Drop them or add the fields. |

### 0.3 Two settled decisions being reopened

`QUESTIONS.md` is a settled record. Two entries are changing and must be amended in place with
a dated note, not silently contradicted:

- **#2 `S` for settings.** It stays bound, and from Phase 1 it *toggles*. Close the entry.
- **#3 the five-line description clamp.** The owner has now asked for an expandable
  description. The clamp stays as the resting state; expansion is opt-in per artwork and
  collapses on rotation. Record the reversal and why.

---

## Phase 1 — The display: readability, typography, controls

The definition of done in `CLAUDE.md` applies hardest here: open it in a browser and look at it,
against a bright artwork and a dark one.

### 1.1 Readability on bright artworks

The overlay is a fixed black gradient (`0.82 → 0.55 → transparent`) with `--fg-dim: #9a9793`.
Over a white-ground print that is marginal, and the top edge of the overlay has no scrim at all.

- Drive the scrim from data we already have. `ArtworkResponse.color` carries HSL from AIC and
  `display.js` already reads `h` and `s` for the background tint. Read `l` too and set a CSS
  custom property on `<body>`: light artworks (`l > 60`) get a stronger, taller gradient.
  One property, two values, no new API field.
- Add `text-shadow: 0 1px 3px rgba(0,0,0,0.6)` to overlay text. It costs nothing at rest and
  rescues the case where the scrim alone is not enough.
- Raise `--fg-dim` to roughly `#b9b6b2`. Check the result against WCAG AA for body text over the
  weakest point of the scrim — `docs/product-spec.md` asks for "sufficient contrast" and that is
  the only measurable reading of it.
- Give `.status` a `backdrop-filter: blur(6px)` and a stronger background; it sits over the
  middle of the artwork, where there is no scrim at all.

### 1.2 Typography

The app is set entirely in `system-ui` at 14px. It reads like a settings dialog.

Split the voice in two:

- **Museum text** — title, artist, date, medium, description — in a serif. Self-host one OFL
  family in `frontend/fonts/` as `woff2`, `font-display: swap`, with a real serif fallback stack.
  **EB Garamond** (regular + semibold, ~45KB each), chosen by the owner over the Source Serif 4
  recommendation. It is the more museum-like face and the harder one to set: Garamond-style
  designs run light on screen, so the type scale below is a requirement of the choice rather
  than a polish pass. No CDN — the app must work with no network, and ADR-0005's
  "the source in the browser is the source in the repository" applies to fonts too.
  `.gitattributes` already treats `woff2` as binary.
- **Interface text** — settings panel, status pill, AI section labels — stays `system-ui`. It
  should look like an interface, because it is one.

Also raise the type scale, further than a sans would have needed: title to ~1.75rem with tighter
tracking, description to ~1.0625rem with `line-height: 1.6`, and widen `.overlay-panel` from
`62ch` to about `68ch` to match. Garamond's small x-height is why the last two are not optional.

Nothing here needs a build step and nothing needs an ADR. Note the font choice and its licence
in `docs/product-spec.md`.

### 1.3 Expandable description (the `i` affordance)

Reverses `QUESTIONS.md` #3 at the owner's request. Keep the ambient character:

- The five-line clamp stays as the resting state.
- A small `i` button sits in the overlay next to the description, shown only when the text is
  actually clamped (measure `scrollHeight > clientHeight`, do not guess from character count).
- Activating it removes the clamp and lets the description scroll inside a bounded box
  (`max-height: 45vh`, `overflow-y: auto`). Collapse on rotation, on `Esc`, and when the overlay
  fades — an expanded essay must never be what an unattended display settles on.
- `.overlay` currently sets `pointer-events: none`, deliberately, so it cannot swallow the
  mousemove that reveals it. Do **not** lift that on the overlay. Set `pointer-events: auto` on
  the individual buttons only.
- Keyboard: the button is a real `<button>` in the tab order. `I` keeps its current meaning
  (pin/unpin the whole overlay) — do not overload it.

### 1.4 `S` toggles, so fullscreen is escapable

`main.js` binds `onSettings: () => void panel.show()`. Pressing `S` twice does nothing, and in
fullscreen `Esc` is taken by the browser to leave fullscreen — so with the panel open in
fullscreen there is no keyboard way to close the panel without also dropping out of fullscreen.

- `onSettings` becomes `panel.isOpen() ? panel.hide() : void panel.show()`.
- Verify in a real browser that the panel renders while `document.documentElement` is the
  fullscreen element (it should — it is a descendant — but this is exactly the class of thing
  the project has been caught by before, and only a human keypress can enter fullscreen).
- Update the keyboard map in `docs/product-spec.md` and `README.md`.

### 1.5 Manual "next artwork" control

`Space` already advances and has no cooldown. Add a visible control and a cooldown to both.

- The control lives **inside the overlay**, next to the `i` button. The overlay is hidden at
  rest, so "no visible controls at rest" is preserved.
- One shared cooldown of **1500ms** guards the button and `Space`. During it the button is
  `disabled` and dimmed; a repeat press is ignored, never queued.
- The cooldown is a frontend concern only. The backend limit in Phase 2 is the real ceiling.

---

## Phase 2 — Rate limiting that matches the real cost

Worth being precise about what actually leaves the machine. With an index present,
`/api/artwork/random` makes **no** AIC API call at all (ADR-0003's second postscript). The
outbound traffic per advance is **one IIIF image fetch**, either direct from the browser or
through `GET /api/image/{image_id}`. So the thing to limit is advances, and the endpoint that
matters most is the image proxy.

Proposed, and tunable:

- `app/domain/rate_limit.py` — a pure token bucket. No clock of its own: the caller passes
  `now`, which is what keeps it unit-testable like everything else in `domain/`.
- Applied as a FastAPI dependency to `/api/artwork/random` **and** `/api/image/{image_id}`.
- **Burst 10, refill 1 per 3s** (20/min sustained) — a human clicking "next" repeatedly gets
  ten immediately and then one every three seconds, which is faster than anyone can look.
- **Rolling ceiling of 400 requests/hour.** The fastest rotation rung is 30s = 120/hour, so this
  leaves ~280 manual advances an hour and still bounds a runaway tab.
- Over the limit: `429` with `Retry-After` and `detail: "too_many_requests"`. The frontend shows
  a calm one-line message from `locales/` and does **not** retry-storm; it waits out
  `Retry-After` and re-arms.
- Config: `MANUAL_ADVANCE_COOLDOWN_MS` in the frontend, and `RATE_LIMIT_*` fields on `Settings`
  so the numbers are tunable without an edit to logic.

This is not about AIC's documented 60 req/min — the index already keeps us far below it. It is
about not being rude to a CDN and not letting a stuck tab run all night.

---

## Phase 3 — Canonical facets: cleanup, exclusion, dependency, Polish

The largest phase, and the one with the most leverage. **It needs no AIC traffic at all** — the
raw terms are already in SQLite.

### 3.1 What is actually wrong with the vocabulary

Measured against the live index:

- **Styles** (92 clear the 40-artwork bar): `19th century` (4,266) and `nineteenth century`
  (688) are separate. So are `18th Century` / `eighteenth century`-shaped pairs across the whole
  century range. `andes` (1,106), `andean` (1,098), `south american` (451) and
  `Arts of the Americas` (1,316) / `americas` (1,154) / `Pre-Columbian` (1,081) all overlap.
  `moche` (361) and `mochica` (219) are the same culture. Casing is inconsistent
  (`Japanese (culture or style)` beside `egyptian`), and several values carry parenthetical
  disambiguators meant for a cataloguer, not a viewer.
- **Subjects** (216 clear the bar): `portrait` (1,612) and `portraits` (1,557); `landscape` /
  `landscapes`; `man` / `men` / `Male` / `portraits: male subject`; `religion` / `religious` /
  `religious figures` / `religious scenes` / `Christianity` / `Christian subjects`;
  `blue` (188) and `blue (color)` (232). And terms that are not subjects at all:
  **`Collected by Hugh Edwards` is the third most common subject with 1,240 artworks**, and
  `lundberg collection` has 397. Those are provenance.
- **Artwork type** (a closed list of 45): `Arms` (497) beside `Armor` (336);
  `Furniture` (372) beside `Furnishings` (67); `None` (3), `non-art` (51), `Materials` (1),
  `Equipment` (4) are not usable filters.

`docs/aic-api.md` already records the portrait/portraits split and the Hugh Edwards term as
"things that look like bugs and are not". They are not bugs in AIC. They are unusable in a
settings panel, which is a different claim.

### 3.2 The design

**One canonical facet layer, three groups, one code path.**

`app/domain/vocabulary.py` — pure, no I/O, the only place the editorial judgement lives:

```python
FacetGroup = Literal["type", "style", "subject"]

@dataclass(frozen=True)
class Facet:
    key: str                    # "style.japanese" — stable, the API value and the i18n suffix
    group: FacetGroup
    label_en: str               # the fallback label, and the answer to "what did we call it"
    members: frozenset[str]     # raw AIC values it absorbs, matched case-insensitively

FACETS: Final[tuple[Facet, ...]] = (...)
DROPPED: Final[frozenset[str]] = frozenset({...})   # provenance and non-subjects, with a comment each

def facets_for(group: FacetGroup, raw_values: Iterable[str]) -> set[str]: ...
```

Rules for the map, written down because the next person will have to extend it:

- **Nothing is invented.** A facet only ever absorbs raw values AIC actually returns. If a facet
  would have no members, it does not exist.
- **Dropping is explicit.** Every dropped value is listed in `DROPPED` with a one-line comment.
  Silence is how a vocabulary rots.
- **Raw data is never destroyed.** `artwork_terms` and `artwork_index.artwork_type` keep AIC's
  own values forever. The facet layer is derived and rebuildable.
- Aim for roughly 50–60 facets per group — see decision 7. Merge the unambiguous
  duplicates and drop the non-subjects; where a fold is a judgement call, leave the values
  apart. A shorter list would read better and would be making choices on the viewer's behalf.

**Storage** — migration 008:

```sql
CREATE TABLE IF NOT EXISTS artwork_facets (
    artwork_id INTEGER NOT NULL REFERENCES artwork_index(id) ON DELETE CASCADE,
    facet      TEXT    NOT NULL,
    PRIMARY KEY (artwork_id, facet)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_artwork_facets_facet ON artwork_facets (facet);
```

Artwork type goes in here too, as `type.*`. That is the point: filtering, counting, exclusion and
dependent counts become **one** query shape for all three groups instead of one for a column and
another for a join table. The primary key also dedupes for free, which matters because two raw
values collapsing into one facet would otherwise double-count.

**Population** — `scripts/build_index.py --retag`: reads `artwork_index.artwork_type` and
`artwork_terms` out of SQLite, applies `vocabulary.facets_for`, rewrites `artwork_facets`
wholesale. No network. Runs in seconds over 57,607 rows. Also run automatically at the end of a
crawl, next to the existing rescore, so fresh rows are never untagged.

**Repository** (`ArtworkIndexRepository`):

- include: `id IN (SELECT artwork_id FROM artwork_facets WHERE facet = ?)`, one per chosen facet,
  ANDed — unchanged semantics from today.
- exclude: `id NOT IN (SELECT artwork_id FROM artwork_facets WHERE facet IN (…))`.
- counts: `SELECT facet, COUNT(*) … GROUP BY facet`, optionally constrained by the rest of the
  selection (below).

### 3.3 Exclusion

Product-spec's reasoning for radios stands — "landscape AND portraits" narrows to nothing — so
**inclusion stays one value per group**. Exclusion is different: excluding several things at once
is normal and does not collapse the result set.

- UI: each group keeps its radio list, and gains a collapsed **"Exclude"** sub-list of
  checkboxes below it. The currently included value's checkbox is disabled.
- API: `/api/artwork/random?exclude=subject.nudity&exclude=type.coin` (repeatable), and
  `PreferencesResponse.exclude: list[str]` with a length cap.
- Guardrail: if include + exclude match nothing, return the existing `404 no_matching_artwork`
  and let the panel say so. Do not silently drop an exclusion.

### 3.4 Dependent counts between Style and Subject

Standard leave-one-out faceting, which is the version that does not over-constrain:

- `GET /api/filters` accepts the current selection and returns, for each option, the count it
  would yield **under the other groups' selections** — so choosing a style updates subject and
  type counts, but the style list you are standing in does not collapse around your own choice.
- Every option stays visible. Options whose constrained count is zero are shown `disabled` with
  `(0)`, not removed — a list that reshuffles under the cursor is worse than a greyed row.
- `MIN_FILTER_COUNT` (40) still decides what is *offered at all*, and is evaluated
  unconstrained, once. It is not re-applied to the constrained counts.

### 3.5 Polish, properly

Today filter values are AIC's English data and are deliberately untranslated. The canonical
layer changes that: a facet label is **our** word, not the museum's data, so it belongs in
`locales/` like every other string (`CLAUDE.md`, and `frontend/CLAUDE.md`'s "every user-visible
string comes from `locales/`").

- Key shape: `facet_style_japanese`, from `key.replace('.', '_')`.
- The API sends `{key, count, label_en}`. The frontend uses `t()` and falls back to `label_en`
  when a key is missing, so an un-translated facet degrades to English rather than to a slug.
  That needs a small `t(key, params, fallback)` addition in `i18n.js`.
- Draft the Polish as **UI copy, not translation** — the owner rewrites literal translations to
  be shorter and idiomatic, so write it that way the first time.
- Also finish the strings the panel already has: `filters_too_thin` in `pl.json` currently reads
  as being about types only, and the mode option strings use em dashes (see Phase 4).

### 3.6 ADR-0009

Write it: *Canonical facet vocabulary over AIC's raw terms*. It closes off "show the museum's
own words", which is a defensible alternative and is what the app does today. Consequences to
state plainly: the app now carries an editorial map that must be maintained as AIC's vocabulary
drifts, and `--retag` is the cheap way to fix it.

---

## Phase 4 — Mode wording, and explaining the score

### 4.1 Mode options

`mode_random_option` is `"Random — anything in the collection"`. The em dash is doing a job a
layout should do.

Render each mode as a **name on one line and a description on a second, quieter line**, with
separate i18n keys (`mode_random`, `mode_random_hint`, …). Same for the third mode arriving in
Phase 5. Drop the dashes from the strings entirely.

### 4.2 The `i` next to Mode

A short, human explanation of Curated scoring, in both languages, opened by an `i` button beside
the Mode legend.

Take the numbers from the code, not from prose that will drift: add
`GET /api/scoring` returning `[{name, weight, share}]` built from `domain.scoring.WEIGHTS`, and
pair each `name` with an i18n key holding one plain sentence. The panel shows a two-sentence
intro, the six signals with their share of the total, and the honest caveat that already exists
in `scoring.py` — these are product heuristics about what suits a screen, not claims about art
(`QUESTIONS.md` #11). Retuning a weight then updates the UI automatically.

Keep it to a paragraph and a list. This is an ambient display.

---

## Phase 5 — Favourites, and "For you"

### 5.1 Storage

Migration 009:

```sql
CREATE TABLE IF NOT EXISTS artwork_feedback (
    artwork_id INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('like', 'hide')),
    title      TEXT,
    artist     TEXT,
    image_id   TEXT,
    created_at TEXT NOT NULL
);
```

**No foreign key to `artwork_index`, deliberately.** An artwork can be liked while it is being
served from AIC or from the bundled fallback set, when it is not in the index at all — and
`PRAGMA foreign_keys=ON` is set, so an FK would turn that into a crash. The small snapshot
(`title`, `artist`, `image_id`) means a favourite survives a rebuilt index and can still be
listed and displayed. One row per artwork: liking something hidden replaces the hide.

`repositories/feedback.py`, matching the existing `*_sync` + `asyncio.to_thread` pattern.

### 5.2 Interaction

- `L` likes / unlikes the artwork on screen; a heart in the overlay shows the state, and a
  `flashStatus` confirms it.
- `X` hides it: never show this artwork again. A hard exclusion in every mode.
- `GET /api/favorites`, `PUT /api/favorites/{id}`, `DELETE /api/favorites/{id}`.
- Settings gains "Favourites only" as a filter, sitting with the facet groups.
- Update the keyboard map in `docs/product-spec.md`, `README.md` and `shortcuts.js`, and add a
  Playwright flow — the existing five are the smoke suite and a sixth is justified here because
  it crosses the whole stack.

### 5.3 "For you" — a third mode, not a change to Curated

Decided: Curated stays reproducible and provider-independent, so ADR-0006's transparency claim
survives intact and `--explain` keeps meaning what it says.

- `app/domain/affinity.py`, pure: given the facets of liked artworks (and hidden ones as a
  negative), build an `AffinityProfile` of per-facet weights, and score a candidate against it.
  Mirror `scoring.py` exactly — one weights dict, one comment per signal, and an `explain()`
  that prints the working. "You are seeing this because you liked 7 Japanese prints" has to be
  something the code can actually say.
- Selection in `personal` mode: sample a pool from the index as today, then rank in Python by
  `curated_score × (1 + α · affinity)`. In Python, not SQL — the profile changes with every like
  and belongs in `domain/`, not in a query.
- **Cold start:** below ~5 likes there is nothing to personalise from. The mode falls back to
  Curated behaviour and the panel says so in one line. Do not show an empty screen and do not
  pretend.
- `PreferencesResponse.mode` becomes `Literal["random", "curated", "personal"]`.
- ADR-0010: *Personalisation from explicit feedback only.* No implicit signals — no dwell time,
  no "you did not skip it". A single-user local app has no data to learn from and inferring
  intent from silence is how this becomes unexplainable.

### 5.4 The two extra personalisation ideas

Both fall out of the layers above almost for free, which is why they are the ones worth having:

1. **Hide / "not this one"** (`X`, above). The negative counterpart of a like. It is the feature
   people actually want from an ambient display — one bad artwork at 3am is memorable in a way a
   good one is not — and it costs one extra value in a `CHECK` constraint.
2. **"More like this."** From the overlay, pin the current artwork's own facets as a temporary
   filter for the next handful of rotations, then release automatically. It is a recommender's
   payoff without a recommender, built entirely on Phase 3's facet table, and it needs no new
   storage at all.

Both are proposals. Neither is in the roadmap until the owner says so.

---

## Phase 6 — Data, indexing, and a new machine

### 6.1 What is actually in `data/vitrine.db`

Eight tables, and they are not the same kind of thing:

| Table | Kind | If lost |
|---|---|---|
| `artwork_index`, `artwork_terms`, `artwork_facets` | Rebuildable corpus | Re-run the walk (~30 min) or fetch the export |
| `interpretations`, `ai_usage` | Rebuildable cache / counters | Costs money to regenerate; nothing breaks |
| `preferences`, `history` | Small user state | Mildly annoying |
| `credentials` | **A secret**, when there is no OS keyring | The API key |

That last row is the whole answer to "can the index be public": **the file that holds the index
also holds an API key**, so `data/vitrine.db` must never be committed, published, or attached to
an issue. Keeping it gitignored is correct and stays.

### 6.2 Is the *corpus* publishable? Yes, with attribution

The index holds AIC metadata for public-domain works and no image bytes. AIC's collection data
is CC0; the `description` field is CC BY 4.0 and requires attribution
(`docs/aic-api.md`, ADR-0007). So a corpus-only export can be redistributed as long as it carries
the attribution — which the app already shows whenever a description is on screen.

### 6.3 Should the database be committed to Git? No

- 60MB of binary that Git stores in full on every rebuild, and it is rebuilt whenever the crawl
  or the scoring changes. The repository is 3MB today.
- It is a derived cache with a staleness policy (ADR-0003), not a source artefact. Sources belong
  in Git; caches do not.
- And it currently contains a secret (6.1).

Git LFS was considered and rejected: it adds a tool, a quota and a checkout failure mode for a
file that is regenerated by one command.

### 6.4 What to build instead

- `scripts/export_index.py` → `dist/vitrine-index.sqlite`, containing **only**
  `artwork_index`, `artwork_terms`, `artwork_facets` and `schema_migrations`, `VACUUM`ed. It
  copies allow-listed tables into a fresh file rather than deleting from a copy of the live one,
  so a table added later cannot leak by default. Expect roughly 25–35MB after `VACUUM`; report
  the real size once it exists.
- `scripts/fetch_index.py` → downloads a published export and merges it into `data/vitrine.db`
  via `ATTACH` + `INSERT OR REPLACE`, leaving `preferences`, `history` and `credentials` alone.
  It must refuse to run against a URL it cannot verify the size and shape of.
- Publish the export as a **GitHub Release asset**. Not in the tree, versioned, easy to replace
  when the corpus is re-walked.
- ADR-0011: *Distribute the index as a release asset, never in Git.*

### 6.5 `docs/setup.md`

Does not exist. The README quick start is close but assumes too much. Write, and verify by
following it on a clean checkout:

- Prerequisites: Python ≥3.12, `uv` (with the pip fallback), and Windows/macOS/Linux notes —
  this repository is developed on Windows and `.gitattributes` normalises line endings for a
  reason.
- `.env` from `.env.example`, and **`AIC_USER_AGENT` is the one line you must actually change**
  (Phase 0.1 makes the app warn about it).
- `uv sync --all-extras`, and what each extra buys: `keyring` decides whether a pasted API key is
  encrypted, `e2e` needs `playwright install chromium` as a separate step.
- Three ways to get an index — `fetch_index.py`, `--limit 5000` for a quick partial, or the full
  walk — and the standing rule that **the full walk needs the owner's approval** because it is
  1,328 requests over ~30 minutes (`CLAUDE.md`, `QUESTIONS.md` #8).
- How to verify: `/api/health`, `/api/stats` (`indexed_artworks`), then a browser.
- Troubleshooting: Chrome caches ES modules hard after a JS edit; `*.db-wal` / `*.db-shm` are
  normal; a missing keyring backend is a warning, not a failure.

### 6.6 `docs/data.md`

The table in 6.1, the licensing position in 6.2, the staleness policy (the index is a cache; AIC
can unpublish an image at any time; a dead image at display time skips), and the refresh
procedure. This is the document that stops the next person from committing the database.

---

## Phase 7 — Additional art sources: research and an ADR, no build

Decided: write it up, propose the boundary, build nothing.

Candidates, with the facts that decide it:

| Source | Key | Limit | Public-domain flag | Images | Fit |
|---|---|---|---|---|---|
| **Cleveland Museum of Art** | None | Not published | `share_license_status == "CC0"` | 900px / 3400px / TIFF, plus IIIF | **Best fit.** ~64k records, no key, CC0 dataset, a clean per-record licence flag, and metadata shaped very like AIC's. |
| **The Met** | None | 80 req/s | `isPublicDomain` bool | `primaryImage` / `primaryImageSmall` direct JPEG | Good. Huge (~490k open-access images). No IIIF and no width ladder, so `chooseWidth()` has nothing to choose from — a real difference from AIC. Search cannot filter to public domain; you filter per record. |
| **Rijksmuseum** | None as of the 2025 data-services move | Not published | Per-object rights | IIIF | Good imagery, but the API was rebuilt recently and the older endpoints are being retired — a moving target. |
| **Harvard Art Museums** | **Required** | 2,500 calls/day | Per-object | IIIF | The key and the daily cap fight ADR-0002's "no accounts, runs on your machine". Indexing alone would take days. |
| **Smithsonian** | Required (api.data.gov) | Per-key | CC0 subset | Mixed | 4.5M records, mostly not paintings. Poor signal-to-noise for an ambient art display. |
| **Europeana** | Required | Per-key | Per-object, heterogeneous | Varies wildly | Aggregator: metadata quality and image availability vary by contributing institution. Would undermine Curated scoring, which leans on consistent fields. |

**Recommendation: Cleveland second, if a second is ever wanted.** No key, CC0, comparable
metadata, and it would genuinely test whether the architecture's boundaries hold.

**ADR-0012 (Proposed, not Accepted)** should say what a second source actually costs, because it
is more than a client:

- `ArtworkSource` is already named as an interface in `docs/architecture.md` but only AIC
  implements it. A second source makes `providers/aic/` one of several and pushes the
  "only the AIC client knows AIC's shape" rule up a level.
- `artwork_index` needs a `source` column and a composite key — artwork id 1 exists at both
  museums. That is a migration touching every read path.
- The IIIF base is currently a single remembered value in `preferences`; it becomes per-source.
- The Met has no IIIF width ladder, so `chooseWidth()` and ADR-0008's proxy assume something the
  Met does not provide.
- Every user-facing string that says "the Art Institute of Chicago" — including the attribution,
  which is a licence condition — becomes per-artwork.

That list is the value of the ADR. It is why this is research, not a phase.

---

## Phase 8 — Reconcile and hand over

Last, once the phases above have moved the code:

- Re-read the ADRs against the code as M6 did, and add postscripts where reality moved. Expect
  ADR-0003 (facet table), ADR-0006 (a second, personal ranking exists alongside it) and
  ADR-0002 (favourites are user data the app now keeps) to need one.
- Update `docs/architecture.md`'s persistence and frontend sections for real this time.
- Re-tick `docs/roadmap.md`.
- Rewrite `HANDOFF.md` again to the state it is actually in.

---

## Recommended architectural changes, in one list

1. **`artwork_facets`, and artwork type folded into it.** One filter code path for all three
   groups instead of a column special case plus a join table. Everything in Phase 3 depends on it.
2. **`domain/vocabulary.py` as the single editorial layer.** Pure, testable, re-runnable with
   `--retag` and no network. Raw AIC values are never overwritten.
3. **`domain/rate_limit.py` as a pure token bucket**, injected as a dependency. Keeps the policy
   out of the route and testable without a clock.
4. **`domain/affinity.py` beside `domain/scoring.py`**, same shape, same explainability
   contract — and a separate mode, so Curated stays what ADR-0006 says it is.
5. **`artwork_feedback` without a foreign key**, carrying a small snapshot. The alternative
   crashes on the fallback path.
6. **A corpus-only export as a distinct artefact.** The live database mixes a rebuildable cache
   with a secret; the export is how you share one without the other.
7. **`GET /api/scoring`** so the UI's explanation of the weights cannot drift from the weights.
8. **Fonts self-hosted in the repository.** No CDN, no build step, works offline — the same
   reasoning ADR-0005 already applies to JavaScript.

Nothing here adds a layer, a framework, or a dependency. That is deliberate: `docs/architecture.md`
says not to add one to "be clean", and none of this needs one.

---

## Decisions taken (owner, 2026-09-03)

1. **Vocabulary — canonical facets, remapped.** Synonyms folded, non-subjects dropped, our own
   translatable labels. Raw terms stay in SQLite.
2. **Index distribution — export plus release asset.** `data/vitrine.db` stays out of Git.
3. **Personalisation — a separate "For you" mode.** Curated is not touched.
4. **Additional sources — research and an ADR only.** Nothing built.

## Decisions taken (owner, 2026-09-03, at the top of M8)

5. **Font — EB Garamond.** Not the recommendation, which was Source Serif 4. The consequence
   was flagged when it was asked and is now a constraint on 1.2 rather than a surprise:
   EB Garamond runs light on screen, so the type scale has to go further than "raise the title".
   The description needs roughly 1.0625–1.125rem and a heavier weight than the face's regular
   before it holds at overlay size. Check it against a bright artwork, not a dark one.
6. **Rate limits — as proposed.** Burst 10, refill 1 per 3s, rolling ceiling 400/hour, tunable
   from `Settings`. See Phase 2.
7. **Facet cleanup — broad, roughly 50–60 per group, not 25–35.** Merge only the unambiguous
   synonyms (`portrait`/`portraits`, `19th century`/`nineteenth century`, `moche`/`mochica`) and
   drop only what is not a subject at all (provenance: `Collected by Hugh Edwards`,
   `lundberg collection`). Where a fold is a judgement call rather than an obvious duplicate —
   `andes` against `andean` against `south american`, say — **leave them apart**. The rejected
   alternative was a "more" control over the raw values behind a canonical top 30; it was
   rejected because it means two tiers in the panel and two code paths, canonical and raw, for
   one question. This rewrites the "aim for roughly 25–35 facets per group" line in Phase 3.2.

## Assumed, not ruled — proceeding, and easy to reverse

1. **"the owner" as the neutral name.** Applied in M7 throughout `CLAUDE.md`, `QUESTIONS.md` and
   `docs/roadmap.md`. Say if you would rather it read "User", or your GitHub handle; it is one
   substitution.
2. **The `AIC_USER_AGENT` default is a placeholder**, not a generic project address, and the app
   warns at startup while it is still in place. Applied in M7. The reasoning: a generic address
   would silence the warning without giving AIC anyone they could actually reach.

## Still needs a ruling

1. **The two extra personalisation ideas** — hide, and "more like this". `X` to hide is in the
   roadmap as part of M11 and is being built; **"more like this" is not**, and stays a proposal
   until you say otherwise.
