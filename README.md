# LogIQ RCA v2

Graph-based Root Cause Attribution platform centered on a **JIRA-first RCA workflow**: normalize a JIRA ticket and logs, run deterministic RCA against Neo4j graph context, persist evidence bundles and investigation history, and return GraphRAG-assisted explanations when an LLM is available.

## Primary workflow

```text
JIRA ticket (+ logs)
  → jira_service (fetch / normalize)
  → jira_rca_orchestration_service
  → deterministic RCA engine (rca_engine/)
  → Neo4j graph + evidence bundle (artifacts/)
  → GraphRAG explanation (graphrag/)
  → API response + investigation history
```

**Entry point:** `POST /api/v1/jira/rca/run`

## Active modules

| Package | Role |
|---------|------|
| `api/` | FastAPI service: JIRA RCA, RCA, feedback, auth, users, jobs |
| `api/services/jira_*` | JIRA integration and JIRA-first RCA orchestration |
| `rca_engine/` | Deterministic RCA (signals, candidates, ranking) |
| `graph/` | Neo4j graph client, writer, ontology docs |
| `graphrag/` | LLM-assisted explanation layer (does not replace RCA) |
| `gates/` | Pre-RCA and post-ingestion quality gates |
| `artifacts/` | Evidence bundle + investigation record storage |
| `jobs/` | Celery RCA jobs and distributed locking |
| `db/` | Postgres (users) and Neo4j (jobs, anomalies) |
| `schemas/` | Shared Pydantic models |
| `security/` | Password hashing, tokens, validation |

Per-folder **`README.md`** files describe package layout (e.g. `api/README.md`, `rca_engine/README.md`, `graphrag/README.md`).

## API endpoints

### JIRA-first RCA

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/jira/tickets/search` | Search JIRA issues |
| `GET` | `/api/v1/jira/tickets/{ticket_key}` | Fetch and normalize a ticket |
| `POST` | `/api/v1/jira/rca/run` | Ticket + logs → deterministic RCA + explanation |
| `GET` | `/api/v1/jira/investigations` | Paginated investigation history |
| `GET` | `/api/v1/jira/investigations/{id}` | Single investigation record |

### RCA and feedback

| Method | Path |
|--------|------|
| `POST` | `/api/v1/rca/run/{anomaly_id}` |
| `POST` | `/api/v1/rca/rerun/{anomaly_id}` |
| `GET` | `/api/v1/rca/results/{anomaly_id}` |
| `GET` | `/api/v1/rca/result-view/{anomaly_id}` |
| `GET` | `/api/v1/rca/run-status/{anomaly_id}` |
| `POST` | `/api/v1/feedback/confirm/{anomaly_id}` |
| `POST` | `/api/v1/feedback/reject/{anomaly_id}` |
| `POST` | `/api/v1/feedback/reject-all/{anomaly_id}` |
| `POST` | `/api/v1/feedback/rollback/{anomaly_id}` |

### Auth, users, jobs

- `POST /api/v1/users`, auth routes under `/api/v1/auth/*`
- `POST/GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`
- `GET /health`

## Email (account verification and password reset)

Configure `EMAIL_PROVIDER` (`log`, `smtp`, or `resend`) in a root `.env` (see `.env.example`). Details: `api/email/`, `api/services/auth_lifecycle.py`.

## Quick start

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Smoke checks:

```bash
python scripts/smoke_test_graph.py
python scripts/smoke_test_rca_api.py
python scripts/smoke_test_graphrag.py
```

## Repository layout

```text
log-analysis-AI-agent/
├── api/
├── artifacts/
├── db/
├── evaluation/
├── feedback/
├── gates/
├── graph/
├── graphrag/
├── ingestion/
├── jobs/
├── rca_engine/
├── schemas/
├── scripts/
├── security/
├── services/
└── tests/
```
