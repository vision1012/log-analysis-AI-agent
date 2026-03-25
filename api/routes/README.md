# `api/routes/`

Additional route modules (kept separate from `routers/` for newer surfaces).

| File | Purpose |
|------|---------|
| `jobs.py` | `POST/GET /api/v1/jobs` and `GET /api/v1/jobs/{job_id}` — validates users in Postgres, jobs in Neo4j; maps domain errors to HTTP status. |
| `__init__.py` | Package marker. |
