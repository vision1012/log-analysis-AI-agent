# `services/` — application services (jobs)

Orchestration layer that sits **above** `db/` repositories and **below** HTTP routers.

| File | Purpose |
|------|---------|
| `jobs_service.py` | Validates users in Postgres (read-only session), creates jobs in Neo4j, resolves `triggered_by_user_id` for job detail; maps domain errors (`UserNotFoundError`, `JobNotFoundError`, etc.). |

RCA and feedback orchestration lives under **`api/services/`** (`rca_service.py`, `feedback_service.py`).
