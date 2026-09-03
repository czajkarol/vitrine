-- What the AI has cost so far, per day and provider. The daily cap in docs/ai-system.md
-- is enforced against this table before a call is made, not reconciled after it.
--
-- One row per day per provider, incremented in place. Nothing here is per-request: a log
-- of individual calls would grow forever to answer a question that is always "how many
-- today".

CREATE TABLE IF NOT EXISTS ai_usage (
    day        TEXT    NOT NULL,
    provider   TEXT    NOT NULL,
    requests   INTEGER NOT NULL DEFAULT 0,
    tokens_in  INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, provider)
);
