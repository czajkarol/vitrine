-- Style and subject, the two multi-valued filters. M3.5.
--
-- A row per (artwork, kind, value) rather than a JSON array in a column on artwork_index.
-- Both work in SQLite, and the deciding factor was what Explore actually asks:
--
--   1. "how many indexed artworks have subject X", for every X, every time the settings
--      panel opens — a filter with too little behind it is not offered at all;
--   2. "give me artworks with subject X", on every rotation while that filter is set.
--
-- Against a join table both are index lookups. Against JSON both need json_each() over
-- every row of artwork_index, and neither can use an index — a full scan of ~57,000 rows
-- to redraw a settings panel, and another on every rotation. The extra table is worth it.
--
-- The cost is that a value is stored as text on every row that carries it, so "landscape"
-- appears thousands of times. At an expected few hundred thousand rows of short strings
-- that is a few megabytes, which is not a consideration on a local SQLite file.
--
-- `kind` rather than two tables: they are queried identically and differ only in which
-- vocabulary the value comes from.

CREATE TABLE IF NOT EXISTS artwork_terms (
    artwork_id INTEGER NOT NULL REFERENCES artwork_index(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('style', 'subject')),
    value      TEXT    NOT NULL,
    PRIMARY KEY (artwork_id, kind, value)
) WITHOUT ROWID;

-- Answers both questions above: the counts per value, and the artworks behind one value.
CREATE INDEX IF NOT EXISTS idx_artwork_terms_lookup ON artwork_terms (kind, value);
