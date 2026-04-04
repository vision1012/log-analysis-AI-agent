# `db/postgres/` — PostgreSQL (users)

Supabase-compatible Postgres: connection string via **`POSTGRES_URL`**.

| File | Purpose |
|------|---------|
| `connection.py` | Lazy singleton SQLAlchemy `Engine`, `sessionmaker`, `get_session()`, `get_db_session()` (commit/rollback), `get_db_session_readonly()` (read paths, no commit). |
| `models.py` | Declarative `Base`, `User` ORM (`users`: `user_id` TEXT PK, `first_name`, `last_name`, `email` unique, `password_hash`, verification/reset columns, `role`, `team`, `created_at`). |
| `repository.py` | `create_user`, `get_user_by_id`, `get_user_by_email`, `list_users` — thin CRUD; ignores unknown keys on create. |

**How it fits:** API/services call repositories inside a session scope; Postgres is the **source of truth for identity**.
