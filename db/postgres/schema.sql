-- PostgreSQL schema for application tables (apply manually or via migration tooling).
-- Source of truth for DDL; SQLAlchemy maps to these tables only (no ORM create_all).

-- 



CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT,
    team TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE users
ADD COLUMN IF NOT EXISTS password_hash TEXT;

UPDATE users
SET password_hash = 'LEGACY_NO_PASSWORD'
WHERE password_hash IS NULL;

ALTER TABLE users
ALTER COLUMN password_hash SET NOT NULL;

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP;

-- Row Level Security: backend connects as `postgres` (bypasses RLS);
-- lock down Supabase anon/authenticated roles from direct REST access.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON users FROM anon;
REVOKE ALL ON users FROM authenticated;
