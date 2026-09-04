-- Saved filter combinations, under a name the user chose. M17.
--
-- **A table rather than a blob in `preferences`, because a preset is a record and not a
-- setting.** `preferences` is single-valued by design — one string per key, and the typed
-- `PreferencesResponse` at the API boundary exists to keep it that way. Presets are
-- plural, have an identity and a name, are listed and deleted individually, and every
-- write to a JSON blob holding all of them would rewrite all of them. Every other plural
-- thing this app remembers — history, feedback, interpretations, usage — is already a
-- table, and this is the same shape.
--
-- **Personal, and therefore never exported.** `repositories/corpus.py` builds a
-- publishable file from an allow-list of corpus tables into a fresh database, so a new
-- table is excluded by not being named there (ADR-0011). That is the whole reason the
-- allow-list is an allow-list, and this migration is the first new table since it was
-- written: it needed no change to stay out.
--
-- The facet lists are comma-separated, the same encoding `preferences` uses for the same
-- values and safe for the same reason — a facet key is `[a-z0-9.-]` by construction and
-- can never contain a comma (`domain/vocabulary.py`, ADR-0014). Not JSON, so the column
-- stays readable to anybody who opens the database, which is the rest of this schema's
-- convention too.
--
-- `name` is UNIQUE, and saving over an existing name replaces it. That is not a
-- compromise around an error case, it is how somebody re-saves a preset they have just
-- adjusted. There is no foreign key to anything: a preset names facets, and a facet is a
-- string the vocabulary may stop offering. What happens then is a display decision, not a
-- storage one — see `docs/product-spec.md`.

CREATE TABLE IF NOT EXISTS filter_presets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    museum       TEXT NOT NULL DEFAULT 'aic',
    artwork_type TEXT NOT NULL DEFAULT '',
    style        TEXT NOT NULL DEFAULT '',
    subject      TEXT NOT NULL DEFAULT '',
    exclude      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- The list is read in full every time the panel opens, newest name first is not what
-- anybody wants, and alphabetical is. One index, one query.
CREATE INDEX IF NOT EXISTS idx_filter_presets_name ON filter_presets (name);
