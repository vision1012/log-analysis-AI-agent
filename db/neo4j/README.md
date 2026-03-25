# `db/neo4j/` — Neo4j (jobs)

Official **`neo4j`** Python driver. Env: **`NEO4J_URI`**, **`NEO4J_USER`**, **`NEO4J_PASSWORD`**.

| File | Purpose |
|------|---------|
| `connection.py` | Lazy singleton `GraphDatabase.driver`, `get_driver()`, `close_driver()`. |
| `jobs_repository.py` | `Job` node CRUD: `create_job` (queued + `created_at`), `get_job`, `list_jobs`, status updates, `mark_job_*` lifecycle helpers. Returns plain dicts; normalizes Neo4j temporal types via `_to_plain`. |
| `init_constraints.py` | `ensure_job_constraints()` — creates uniqueness constraint on `Job.job_id` if missing. |

**How it fits:** Jobs are stored only here; **`triggered_by_user_id`** is a property string, not a relationship to a User node.
