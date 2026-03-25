# `jobs/` — background jobs (RCA)

Optional **Celery**-based background execution for long-running RCA work.

| File | Purpose |
|------|---------|
| `rca_jobs.py` | Celery task definitions for RCA runs (broker/backend from env); logging and retries policy. |
| `job_locking.py` | Distributed lock helpers to avoid duplicate concurrent work on the same anomaly/job. |
| `__init__.py` | Package marker. |

**Note:** HTTP **job** CRUD for the product API lives in **`db/neo4j`** + **`api/routes/jobs.py`**; this folder is for **async worker** jobs.
