-- Enable Row Level Security on the `users` table.
-- The backend connects as the `postgres` role (superuser / owner), which
-- bypasses RLS automatically, so all SQLAlchemy queries keep working.
-- This migration locks down the Supabase auto-generated `anon` and
-- `authenticated` API roles so nobody can read or write user data by
-- hitting the PostgREST (Supabase REST) API directly.

-- 1. Turn on RLS (no-op if already enabled).
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- 2. Revoke blanket table privileges from the public API roles.
REVOKE ALL ON users FROM anon;
REVOKE ALL ON users FROM authenticated;

-- 3. (Optional) If you later want authenticated users to read ONLY their
--    own row through the Supabase client SDK, uncomment the policy below
--    and grant SELECT back to `authenticated`.
--
-- GRANT SELECT ON users TO authenticated;
-- CREATE POLICY users_self_select ON users
--   FOR SELECT
--   TO authenticated
--   USING (user_id = auth.uid()::text);
