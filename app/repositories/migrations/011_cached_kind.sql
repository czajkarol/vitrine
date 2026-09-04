-- The interpretation cache holds two things from M14, and has to be able to say which.
--
-- `kind` is already inside `cache_key` for anything that is not an interpretation — see
-- `CacheKey.as_string`, which appends it only when it is not the default, so no entry
-- written before this migration changed its key. This column exists for the same reason
-- `prompt_version` is a column as well as part of the key: retiring one kind wholesale is
-- a bulk operation, and doing it by string surgery on a primary key is how you delete the
-- wrong rows.
--
-- Defaulted rather than backfilled: every existing row is an interpretation by
-- construction, because there was nothing else to store.

ALTER TABLE interpretations ADD COLUMN kind TEXT NOT NULL DEFAULT 'interpretation';

CREATE INDEX IF NOT EXISTS idx_interpretations_kind ON interpretations (kind);
