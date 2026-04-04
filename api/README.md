# `api/` — HTTP service (FastAPI)

REST entrypoint for RCA, feedback, debug-agent, and jobs. Run with e.g. `uvicorn api.main:app`.

| File / area | Purpose |
|-------------|---------|
| `main.py` | FastAPI app: CORS, observability middleware, router includes (`/api/v1`, debug-agent). |
| `config.py` | Pydantic-style settings: Ollama, dirs, API host/port, timeouts. |
| `debug_agent_routes.py` | Router for debug-agent run/status (orchestrator). |
| `core/` | Shared path helpers (`paths.py`). |
| `middleware/` | Request logging / `X-Request-Id` (`observability.py`). |
| `routers/` | RCA, feedback, health routes. |
| `routes/` | Jobs API (Postgres + Neo4j orchestration). |
| `schemas/` | Small API-local schema package (legacy/compat). |
| `services/` | RCA and feedback service functions used by routers. |
| `utils/` | Package placeholder / shared utils. |

**Note:** Cross-cutting job orchestration also lives in top-level `services/` and `schemas/` (see those READMEs).

**Email (verification / password reset):** Configure `EMAIL_PROVIDER` (`log`, `smtp` e.g. Gmail, or `resend`), `SMTP_*` / `RESEND_*`, `APP_BASE_URL`, etc. in a root `.env` (see repository `.env.example`). Overview in the root `README.md` **Email** section; SMTP in `api/email/provider.py` (`SmtpEmailProvider`).
