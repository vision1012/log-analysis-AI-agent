-- Replace legacy `name` with `first_name` and `last_name` (existing full names preserved).
-- Apply after 001/002 when upgrading a database that still has `users.name`.

ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'users'
      AND column_name = 'name'
  ) THEN
    UPDATE users SET
      first_name = COALESCE(NULLIF(split_part(trim(name), ' ', 1), ''), 'User'),
      last_name = CASE
        WHEN strpos(trim(name), ' ') = 0 THEN ''
        ELSE trim(substring(trim(name) from strpos(trim(name), ' ') + 1))
      END;
    ALTER TABLE users DROP COLUMN name;
  END IF;
END $$;

UPDATE users
SET first_name = COALESCE(NULLIF(trim(first_name), ''), 'User')
WHERE first_name IS NULL OR trim(first_name) = '';

UPDATE users
SET last_name = COALESCE(trim(last_name), '')
WHERE last_name IS NULL;

ALTER TABLE users ALTER COLUMN first_name SET NOT NULL;
ALTER TABLE users ALTER COLUMN last_name SET NOT NULL;
