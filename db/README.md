# `db/` — persistence layers

This package holds **database access code** only (no business orchestration). The system uses **PostgreSQL** for durable user identity and **Neo4j** for graph-shaped job and RCA data.

| Subfolder | Role |
|-----------|------|
| `postgres/` | SQLAlchemy engine, `User` model, user repository |
| `neo4j/` | Official Neo4j driver, `Job` node repository, constraints |

**Environment:** `POSTGRES_URL` (Postgres); `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (Neo4j).

**Separation:** User rows live only in Postgres. Job nodes live only in Neo4j and reference users via `triggered_by_user_id` (string UUID), not via foreign keys.
