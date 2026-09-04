-- Feedback grows two dimensions in M13: a third verdict, and which museum the artwork
-- came from.
--
-- **`dislike` is not `hide`.** `X` means never again and is a hard exclusion from
-- selection. `D` means "less of this", and is a ranking signal only — the artwork can
-- still come round. Folding the two into one kind would have made the softer of them
-- unreachable, because a signal that also removes the thing it is about cannot be soft.
--
-- **`museum` exists because artwork id 1 is a real record at both museums.** Cleveland
-- arrives in M15 and is served live rather than indexed, so nothing else here needs a
-- source column yet — but a favourite keyed on `artwork_id` alone would let a Cleveland
-- print silently un-like an Art Institute painting. ADR-0012 listed this as the first of
-- the eight things a second source costs; this is the part of it that could not be
-- deferred.
--
-- SQLite cannot alter a primary key, so the table is rebuilt. Every existing row is an
-- Art Institute row by construction — there was no other source when they were written.

CREATE TABLE artwork_feedback_new (
    museum     TEXT    NOT NULL DEFAULT 'aic',
    artwork_id INTEGER NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('like', 'dislike', 'hide')),
    title      TEXT,
    artist     TEXT,
    image_id   TEXT,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (museum, artwork_id)
);

INSERT INTO artwork_feedback_new (museum, artwork_id, kind, title, artist, image_id, created_at)
    SELECT 'aic', artwork_id, kind, title, artist, image_id, created_at FROM artwork_feedback;

DROP TABLE artwork_feedback;
ALTER TABLE artwork_feedback_new RENAME TO artwork_feedback;

-- "Every artwork I have hidden" runs on every selection, and "everything I have liked"
-- runs whenever the affinity profile is rebuilt. Both are this index, and both are asked
-- one museum at a time.
CREATE INDEX IF NOT EXISTS idx_artwork_feedback_kind
    ON artwork_feedback (museum, kind, artwork_id);
