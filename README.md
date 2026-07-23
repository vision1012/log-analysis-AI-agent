# LogIQ — AI-assisted Root Cause Analysis

LogIQ is a **JIRA-first, graph-backed RCA platform**. It turns incident tickets and uploaded logs into ranked root-cause candidates using a **deterministic engine**, then optionally enriches the investigation with **MCP integrations** (Jira, GitHub, Datadog, Kubernetes, and more) and an **LLM explanation layer** that narrates evidence without changing the ranking.

## Overview

When an incident lands in Jira, operators need more than a stack dump. LogIQ:

1. **Ingests** a Jira ticket (or ticket key) plus log content
2. **Extracts signals** from logs, stack traces, keywords, and file paths
3. **Ranks candidates** with a deterministic RCA engine against Neo4j graph context
4. **Pulls related context** from workspace MCP connections (commits, deploys, alerts, runbooks)
5. **Explains** the top candidate in plain language via GraphRAG (assistive only — RCA scores stay authoritative)
6. **Stores** investigation history, evidence bundles, and feedback for later learning

The product goal is **trustworthy RCA**: rankings come from explicit signals and graph evidence; the LLM explains those results and must not invent a different root cause.

## Primary workflow

```text
JIRA ticket (+ logs)
  → jira_service (fetch / normalize, workspace DB credentials)
  → MCP orchestrator (optional: GitHub, Datadog, K8s, …)
  → jira_rca_orchestration_service
  → deterministic RCA engine (rca_engine/)
  → Neo4j graph + evidence bundles (artifacts/, graph/)
  → GraphRAG explanation (graphrag/)
  → API response + investigation history
```

**Main entry point:** `POST /api/v1/jira/rca/run`

## MCP integrations

Workspace-scoped connections (stored encrypted in Postgres) can feed investigation context:

| Provider | Context contributed |
|----------|---------------------|
| **jira** | Ticket summary, labels, comments, linked issues |
| **github** | Recent commits, PRs, changed files |
| **gitlab** | Repo / MR context |
| **jenkins** | Build / CI pipeline signals |
| **datadog** | Metrics, alerts, traces |
| **kubernetes** | Pod / deployment runtime signals |
| **pagerduty** | Incidents and escalations |
| **confluence** | Runbooks and known-issue docs |

Enable globally with `MCP_ENABLED=true` and per-provider flags (see `env.example`). Connections are managed via the integration connections API and validated through the MCP connection center.

## Active modules

| Package | Role |
|---------|------|
| `api/` | FastAPI service: JIRA RCA, auth, integrations, investigations, jobs |
| `mcp/` | Provider registry, orchestrator, connection manager, correlators |
| `integrations/` | Workspace connection CRUD + credential encryption |
| `rca_engine/` | Deterministic RCA (signals, candidates, ranking, confidence) |
| `graph/` | Neo4j client, investigation writer / retriever |
| `graphrag/` | LLM-assisted explanation (does not replace RCA ranking) |
| `agents/` | Multi-agent investigation helpers (timeline, deploy, infra, …) |
| `gates/` | Pre-RCA and post-ingestion quality gates |
| `artifacts/` | Evidence bundle + investigation record storage |
| `feedback/` | Confirm / reject / override learning signals |
| `reporting/` | Markdown / PDF investigation reports |
| `jobs/` | Celery RCA jobs and distributed locking |
| `db/` | Postgres (users, connections) and Neo4j |
| `schemas/` | Shared Pydantic models |
| `security/` | Password hashing, tokens, validation |

Per-folder **`README.md`** files describe package layout (e.g. `api/README.md`, `rca_engine/README.md`, `graphrag/README.md`, `mcp/`).

## API endpoints

### JIRA-first RCA

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/jira/tickets/search` | Search JIRA issues (`q` or `jql`; ticket keys use `issuekey`) |
| `GET` | `/api/v1/jira/tickets/{ticket_key}` | Fetch and normalize a ticket (`workspace_id` for DB credentials) |
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

### Auth, users, jobs, health

- `POST /api/v1/users`, auth routes under `/api/v1/auth/*`
- Integration connections under `/api/v1/integrations/*` (workspace-scoped)
- `POST/GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}`
- `GET /health`
- Interactive docs: `http://127.0.0.1:8000/docs`

## Quick start

### Docker Compose (recommended)

```bash
cp env.example .env   # or .env.example — fill secrets
docker compose up -d --build
```

Services:

| Container | Port |
|-----------|------|
| `logiq-api` | `8000` |
| `logiq-redis` | `6379` |
| `neo4j-db` | `7474` / `7687` |

Stop everything:

```bash
docker compose down
```

### Local uvicorn

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Requires reachable Redis / Neo4j (or Docker services) as configured in `.env`.

### Smoke checks

```bash
python scripts/smoke_test_graph.py
python scripts/smoke_test_rca_api.py
python scripts/smoke_test_graphrag.py
```

## Configuration

Copy `env.example` (or `.env.example`) to `.env`. Important groups:

- **Jira / MCP:** `JIRA_*`, `MCP_ENABLED`, `*_MCP_ENABLED`, workspace integration encryption keys
- **Graph:** `NEO4J_URI`, Neo4j auth
- **Rate limits:** `REDIS_URL`, `RATE_LIMIT_*`
- **LLM explanations:** `OLLAMA_HOST` / `GRAPHRAG_LLM_*` (optional; deterministic RCA works without an LLM)
- **Email:** `EMAIL_PROVIDER` (`log`, `smtp`, or `resend`) for verification and password reset

Never commit real secrets.

## Repository layout

```text
log-analysis-AI-agent/
├── api/              # FastAPI app
├── mcp/              # MCP providers + orchestrator
├── integrations/     # Workspace connection store
├── rca_engine/       # Deterministic RCA
├── graph/            # Neo4j investigation graph
├── graphrag/         # Assistive LLM explanations
├── agents/           # Multi-agent investigation helpers
├── artifacts/        # Evidence / investigation persistence
├── feedback/         # Operator feedback learning
├── reporting/        # Report export
├── db/               # Postgres + Neo4j schema
├── schemas/          # Shared models
├── scripts/          # Audits, smoke tests, validators
└── tests/
```

## Design principles

- **Deterministic RCA is authoritative** — candidate ranking and confidence come from the engine, not the LLM.
- **Explanations are assistive** — GraphRAG narrates supplied evidence; inventing root causes is rejected.
- **Workspace credentials over global env** when `workspace_id` is provided — MCP/DB connections are preferred.
- **Evidence stays inspectable** — bundles, signal contributions, and investigation records are queryable via the API.
