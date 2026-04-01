-- Add bcrypt password storage to existing ``users`` tables (idempotent-ish).
-- For new deployments, prefer applying ``db/postgres/schema.sql`` which includes ``password_hash``.
--
-- Steps:
-- 1. Add nullable column.
-- 2. Backfill rows that lack a hash with a bcrypt hash whose plaintext was randomly
--    generated once and discarded — migrated users cannot log in until an operator
--    sets a real password (e.g. via signup replacement flow or future reset).
-- 3. Enforce NOT NULL.

ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;

UPDATE users
SET password_hash = '$2b$12$f66aMvXxPLzSc6zSy6LcreRLsmwetwPRVWWKdOkmJX/yCNk0j58M6'
WHERE password_hash IS NULL;

ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;
