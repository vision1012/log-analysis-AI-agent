-- PostgreSQL schema for application tables (apply manually or via migration tooling).
-- Source of truth for DDL; SQLAlchemy maps to these tables only (no ORM create_all).
--
-- Final ``users`` shape (identity; no legacy single ``name`` column):
--   user_id, first_name, last_name, email, password_hash,
--   is_email_verified, email_verification_*, password_reset_*,
--   role, team, created_at
-- Upgrading from older DBs that had ``name``: see migrations/003_user_first_last_name.sql

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

-- Integration connections (workspace-scoped encrypted provider credentials)
CREATE TABLE IF NOT EXISTS integration_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    display_name TEXT NOT NULL,
    base_url TEXT,
    org_name TEXT,
    project_key TEXT,
    repo_name TEXT,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    encrypted_credentials TEXT NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_validated_at TIMESTAMP,
    last_validation_status TEXT,
    last_validation_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_integration_connections_workspace_id
    ON integration_connections (workspace_id);
CREATE INDEX IF NOT EXISTS idx_integration_connections_provider
    ON integration_connections (provider);
CREATE INDEX IF NOT EXISTS idx_integration_connections_workspace_provider
    ON integration_connections (workspace_id, provider);
CREATE INDEX IF NOT EXISTS idx_integration_connections_is_enabled
    ON integration_connections (is_enabled);

ALTER TABLE integration_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON integration_connections FROM anon;
REVOKE ALL ON integration_connections FROM authenticated;
