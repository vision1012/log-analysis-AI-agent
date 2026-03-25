# `api/middleware/`

ASGI middleware for the FastAPI app.

| File | Purpose |
|------|---------|
| `observability.py` | Adds request correlation (`X-Request-Id`), structured request/response logging; can exclude health/docs paths. |
| `__init__.py` | Package marker. |
