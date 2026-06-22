# `api/` — HTTP service (FastAPI)

REST entrypoint for JIRA-first RCA, deterministic RCA, feedback, auth, users, and jobs. Run with `uvicorn api.main:app`.

| File / area | Purpose |
|-------------|---------|
| `main.py` | FastAPI app: CORS, observability middleware, router includes |
| `config.py` | App settings: Ollama, dirs, API host/port, timeouts |
| `llm_provider_status.py` | LLM provider health snapshot at startup |
| `core/` | Shared path helpers (`paths.py`) |
| `middleware/` | Request logging / `X-Request-Id`, rate-limit context |
| `rate_limit/` | Redis-backed per-scope rate limiting |
| `email/` | Verification and password-reset email delivery |
| `routers/` | RCA, feedback, health, auth, users, JIRA ticket routes |
| `routes/` | Jobs API, JIRA RCA run, investigation history |
| `services/` | RCA, feedback, auth, users, JIRA orchestration |
| `utils/` | Shared helpers (e.g. `jira_http.py`) |

### JIRA-first RCA flow

| Endpoint | Role |
|----------|------|
| `GET /api/v1/jira/tickets/search` | Search issues (text or raw JQL) |
| `GET /api/v1/jira/tickets/{ticket_key}` | Fetch + normalize JIRA issue |
| `POST /api/v1/jira/rca/run` | Ticket + `log_content` → deterministic RCA → GraphRAG explanation → investigation record |
| `GET /api/v1/jira/investigations` | Paginated investigation history |
| `GET /api/v1/jira/investigations/{investigation_id}` | Full stored investigation metadata |

**Contracts:** Normalized ticket shape is `schemas.jira.JiraNormalizedTicket`. Log parsing uses `schemas.jira_rca.DerivedSignalBundle`. Evidence bundle IDs live under **`rca.evidence_summary`**. Assistive explanation status: `explanation_payload.assist_status` (`ok` \| `partial` \| `unavailable`); RCA candidates remain authoritative.

**Email:** See root `README.md` and `api/email/`.
