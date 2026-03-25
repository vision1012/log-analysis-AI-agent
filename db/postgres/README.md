# `db/postgres/` — PostgreSQL (users)

Supabase-compatible Postgres: connection string via **`POSTGRES_URL`**.

| File | Purpose |
|------|---------|
| `connection.py` | Lazy singleton SQLAlchemy `Engine`, `sessionmaker`, `get_session()`, `get_db_session()` (commit/rollback), `get_db_session_readonly()` (read paths, no commit). |
| `models.py` | Declarative `Base`, `User` ORM (`users` table: `user_id` UUID PK, `name`, `email` unique, `role`, `team`, `created_at` timestamptz). |
| `repository.py` | `create_user`, `get_user_by_id`, `get_user_by_email`, `list_users` — thin CRUD; ignores unknown keys on create. |

**How it fits:** API/services call repositories inside a session scope; Postgres is the **source of truth for identity**.
