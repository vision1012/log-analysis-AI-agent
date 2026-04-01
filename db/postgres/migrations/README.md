# PostgreSQL migrations

DDL for application tables lives in [`../schema.sql`](../schema.sql). Apply that file for **new** databases.

If you already have a `users` table **without** `password_hash`, apply migrations in order:

1. **`001_add_password_hash.sql`** — Adds `password_hash TEXT NOT NULL` and backfills existing rows with a one-way bcrypt placeholder (those accounts cannot authenticate until a real password is set through your operational process).

Run against your database (example):

```bash
psql "$POSTGRES_URL" -f db/postgres/migrations/001_add_password_hash.sql
```

After migration, new users created via `POST /api/v1/users` must include a password; it is stored only as a bcrypt hash.
