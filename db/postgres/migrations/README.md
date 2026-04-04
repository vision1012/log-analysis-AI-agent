# PostgreSQL migrations

DDL for application tables lives in [`../schema.sql`](../schema.sql). Apply that file for **new** databases.

If you already have a `users` table, apply migrations in order:

1. **`001_add_password_hash.sql`** — Adds `password_hash TEXT NOT NULL` and backfills existing rows with a one-way bcrypt placeholder (those accounts cannot authenticate until a real password is set through your operational process).

2. **`002_user_email_verification_and_password_reset.sql`** — Adds `is_email_verified`, verification and password-reset token hash/expiry columns; marks existing rows as verified.

3. **`003_user_first_last_name.sql`** — Replaces `name` with `first_name` and `last_name`. Existing full names are split on the first space (first token → `first_name`, remainder → `last_name`; single-word names get an empty `last_name`).

4. **`004_enable_rls_users.sql`** — Enables Row Level Security on `users` and revokes all privileges from the Supabase `anon` and `authenticated` roles. The backend's `postgres` role bypasses RLS as owner, so SQLAlchemy queries are unaffected.

Run against your database (example):

```bash
psql "$POSTGRES_URL" -f db/postgres/migrations/001_add_password_hash.sql
psql "$POSTGRES_URL" -f db/postgres/migrations/002_user_email_verification_and_password_reset.sql
psql "$POSTGRES_URL" -f db/postgres/migrations/003_user_first_last_name.sql
psql "$POSTGRES_URL" -f db/postgres/migrations/004_enable_rls_users.sql
```

After migration, signup sends a verification email; login requires `is_email_verified` unless you use seeded/dev users with verification already set.
