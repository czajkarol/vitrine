-- The AI interpretation cache, promised by 001 and arriving with M5.
--
-- The key is composite by design: artwork, language, provider, model and prompt version
-- all change the answer, so all five are in the primary key rather than only the artwork.
-- It is stored as one text column because that is what the application computes and looks
-- up; the parts are kept alongside it so a prompt-version sweep can delete by column
-- instead of by string surgery.

CREATE TABLE IF NOT EXISTS interpretations (
    cache_key      TEXT    PRIMARY KEY,
    artwork_id     INTEGER NOT NULL,
    language       TEXT    NOT NULL,
    provider       TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    prompt_version INTEGER NOT NULL,
    -- The validated Interpretation, as JSON. Validated again on the way out: a row
    -- written by an older shape must not reach the display unchecked.
    payload_json   TEXT    NOT NULL,
    created_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- For retiring a prompt version wholesale, which is the one bulk operation this table has.
CREATE INDEX IF NOT EXISTS idx_interpretations_prompt_version
    ON interpretations (prompt_version);
