-- Likes and hides. M11, and ADR-0010.
--
-- **No foreign key to artwork_index, deliberately.** An artwork can be on screen without
-- being in the index at all: the display's second and third tiers serve straight from AIC
-- and from the bundled fallback set (ADR-0003), and a fresh clone with no index shows only
-- those. `PRAGMA foreign_keys=ON` is set, so a foreign key here would turn "liked the
-- artwork I am looking at" into an IntegrityError on precisely the setup a new user has.
--
-- The snapshot is why that is safe rather than merely convenient. Title, artist and
-- image_id are copied in, so a favourite survives a rebuilt index, an artwork AIC has
-- unpublished, and an index that never existed — enough to list it and to put it back on
-- screen without going and asking anyone.
--
-- One row per artwork, so `kind` is a state and not a log. Liking something previously
-- hidden replaces the hide rather than leaving the two to argue.

CREATE TABLE IF NOT EXISTS artwork_feedback (
    artwork_id INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL CHECK (kind IN ('like', 'hide')),
    title      TEXT,
    artist     TEXT,
    image_id   TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- "Every artwork I have hidden" runs on every selection, and "everything I have liked"
-- runs whenever the affinity profile is rebuilt. Both are this index.
CREATE INDEX IF NOT EXISTS idx_artwork_feedback_kind ON artwork_feedback (kind, artwork_id);
