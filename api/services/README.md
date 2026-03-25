# `api/services/`

Service functions called by FastAPI routers (RCA and feedback). Keeps route handlers thin.

| File | Purpose |
|------|---------|
| `rca_service.py` | Orchestrates deterministic RCA runs: loads graph context, calls `rca_engine`, writes artifacts, returns view models for the API. |
| `feedback_service.py` | Applies user feedback (confirm/reject/rollback) against graph/candidate state. |
| `__init__.py` | Package marker. |

Job creation/list/detail orchestration lives in **`services/jobs_service.py`** at repo root.
