-- The rotation menu gained a 30-second rung, so the interval is no longer a whole number
-- of minutes and the stored preference changes unit. Converting here rather than in the
-- read path keeps the interpretation of `interval_seconds` in one place: a number of
-- seconds, always, with no era before which it meant something else.
--
-- A value that is not on the current menu is simply dropped. The route already falls back
-- to the default for an unusable stored preference, and carrying a converted 2-minute
-- interval nobody can select again is worse than starting from the default.

INSERT INTO preferences (key, value)
SELECT 'interval_seconds', CAST(CAST(value AS INTEGER) * 60 AS TEXT)
FROM preferences
WHERE key = 'interval_minutes'
  AND CAST(value AS INTEGER) IN (1, 5, 15, 30)
ON CONFLICT(key) DO NOTHING;

DELETE FROM preferences WHERE key = 'interval_minutes';
