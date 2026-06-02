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
| `utils/` | Shared helpers (e.g. `utils/jira_http.py` — stable JIRA error mapping). |

**Note:** Cross-cutting job orchestration also lives in top-level `services/` and `schemas/` (see those READMEs).

### JIRA-first RCA flow (deterministic RCA)

| Endpoint | Role |
|----------|------|
| `GET /api/v1/jira/tickets/search` | Search issues (`q` = simple text → JQL `text ~ "..."`, or `jql` = raw JQL); returns lightweight `issues` + `jql_used` + `total`. |
| `GET /api/v1/jira/tickets/{ticket_key}` | Fetch + normalize JIRA issue; returns `ticket` + `hints`. |
| `GET /api/v1/jira/ticket/{ticket_key}` | **Mock** demo tickets (`LAAA-78`, `LAAA-79`) for RCA UI without live JIRA; 404 if unknown. |
| `POST /api/v1/jira/rca/run` | Ticket context + `log_content` → log signals → run deterministic RCA on `anomaly_id` → `rca`, `explanation_payload`, `relationship_bundle`; persists minimal investigation metadata. |
| `GET /api/v1/jira/investigations` | Paginated history of persisted investigations (no raw logs). |
| `GET /api/v1/jira/investigations/{investigation_id}` | Full stored record for one investigation (metadata + derived snapshots only). |

**Contracts:** Normalized ticket shape is always `schemas.jira.JiraNormalizedTicket`. Merged hints + log parsing use `schemas.jira_rca.DerivedSignalBundle`. Evidence bundle IDs and counts live under **`rca.evidence_summary` only** (not duplicated under `explanation_payload`). Assistive explanation status: `explanation_payload.assist_status` (`ok` | `partial` | `unavailable`); RCA candidates and ranking remain authoritative.

**Errors:** JIRA integration failures use `detail: { "code": string, "message": string }` (see `api/utils/jira_http.py`). Request body validation failures (e.g. missing `ticket`/`ticket_key`, blank `log_content`) return FastAPI’s standard **422** validation response shape.

**Email (verification / password reset):** Configure `EMAIL_PROVIDER` (`log`, `smtp` e.g. Gmail, or `resend`), `SMTP_*` / `RESEND_*`, `APP_BASE_URL`, etc. in a root `.env` (see repository `.env.example`). Overview in the root `README.md` **Email** section; SMTP in `api/email/provider.py` (`SmtpEmailProvider`).
