# `api/routers/`

FastAPI `APIRouter` modules mounted from `api/main.py` (usually under prefix `/api/v1`).

| File | Purpose |
|------|---------|
| `health.py` | Liveness/readiness-style health endpoint. |
| `rca_routes.py` | RCA run/rerun/results/status/explanation endpoints; delegates to `api/services/rca_service.py`. |
| `feedback_routes.py` | Confirm/reject/rollback feedback flows; delegates to `api/services/feedback_service.py`. |
| `__init__.py` | Package marker. |
