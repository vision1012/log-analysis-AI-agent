# `schemas/` — shared Pydantic models (API)

Cross-cutting request/response models used outside a single router file.

| File | Purpose |
|------|---------|
| `jobs.py` | `CreateJobRequest`, `JobResponse`, `JobUserSummary`, `JobDetailResponse` for the jobs API. |

Imported by **`services/jobs_service.py`** and **`api/routes/jobs.py`**.
