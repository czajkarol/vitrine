-- Bring-your-own API keys, when the OS keyring is not available to hold them.
--
-- The fallback tier, not the preferred one: docs/ai-system.md asks for the keyring first
-- and allows this only because the app is local-first (ADR-0002) and the file belongs to
-- the person whose key it is. Anything stored here is unencrypted, the UI says so
-- plainly, and the row exists only because the user pasted a key into the settings panel.
--
-- One row per provider, so switching vendors does not throw away the other key.

CREATE TABLE IF NOT EXISTS credentials (
    provider   TEXT NOT NULL PRIMARY KEY,
    api_key    TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
