-- The local artwork index and the two small tables the display needs alongside it.
-- Interpretation and AI-usage tables arrive with M5, in their own migration.

CREATE TABLE IF NOT EXISTS artwork_index (
    id                    INTEGER PRIMARY KEY,
    image_id              TEXT    NOT NULL,
    title                 TEXT    NOT NULL,
    artist                TEXT,
    date_display          TEXT,
    medium_display        TEXT,
    credit_line           TEXT,
    place_of_origin       TEXT,
    department_title      TEXT,
    -- AIC calls this artwork_type_title. Named for what it is to us: the thing Explore
    -- mode filters on and Curated mode scores.
    classification        TEXT,
    main_reference_number TEXT,
    description           TEXT,
    width                 INTEGER,
    height                INTEGER,
    is_boosted            INTEGER NOT NULL DEFAULT 0,
    has_alt_text          INTEGER NOT NULL DEFAULT 0,
    alt_text              TEXT,
    lqip                  TEXT,
    color_h               INTEGER,
    color_s               INTEGER,
    color_l               INTEGER,
    -- Written by M3's scoring pass. Null until then, which is why sampling must not
    -- assume it is present.
    score                 REAL,
    indexed_at            TEXT    NOT NULL
);

-- Explore mode filters on classification and needs counts per value to decide whether a
-- filter is worth offering at all.
CREATE INDEX IF NOT EXISTS idx_artwork_index_classification ON artwork_index (classification);
CREATE INDEX IF NOT EXISTS idx_artwork_index_score ON artwork_index (score DESC);

CREATE TABLE IF NOT EXISTS history (
    artwork_id INTEGER NOT NULL,
    shown_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_shown_at ON history (shown_at DESC);

CREATE TABLE IF NOT EXISTS preferences (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
