-- Integration connections: workspace-scoped provider credentials (encrypted at rest).
-- Apply after 004_enable_rls_users.sql on existing databases.
-- New databases: also reflected in ../schema.sql.

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

-- Lock down Supabase REST roles (backend uses postgres owner role).
ALTER TABLE integration_connections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON integration_connections FROM anon;
REVOKE ALL ON integration_connections FROM authenticated;
