# Graph-Based RCA Platform (RCA v2)

This repository now centers on a deterministic, graph-based Root Cause Attribution (RCA v2) system.
The active architecture uses Neo4j-backed anomaly context, deterministic candidate scoring, evidence bundles, and feedback-driven attribution status transitions.

`old_log_arch_v1/` contains archived legacy log-agent/RAG code kept for historical reference.

## Active Platform Scope

Primary active modules:

- `graph/` - Graph client, writer, ontology docs, invariants, lifecycle docs
- `rca_engine/` - RCA orchestration (`pre-gate -> candidates -> signals -> ranking -> evidence -> atomic write`)
- `gates/` - Pre-ingestion and pre-RCA quality gates
- `jobs/` - RCA job locking/background task orchestration
- `artifacts/` - Evidence bundle storage interfaces/backends
- `ingestion/` - Ingestion contracts and specs
- `feedback/` - RCA confirmation/rejection workflow docs
- `evaluation/` - RCA metrics definitions
- `api/` - RCA and feedback API routes/services
- `scripts/smoke_test_graph.py`, `scripts/smoke_test_rca_api.py` - Active smoke validation scripts

`machine_learning/` remains in-repo and is retained as requested.

## Per-folder documentation

Each major package has a **`README.md`** describing purpose and files (high level): e.g. `db/README.md`, `api/README.md`, `rca_engine/README.md`, `graphrag/README.md`, `debug_agent/README.md`, `scripts/README.md`, and subfolders such as `db/postgres/`, `db/neo4j/`, `api/routers/`, `machine_learning/features/`, etc.

## API Endpoints (Current)

Active endpoints:

- `GET /health`
- `POST /api/v1/rca/run/{anomaly_id}`
- `POST /api/v1/rca/rerun/{anomaly_id}`
- `GET /api/v1/rca/results/{anomaly_id}`
- `GET /api/v1/rca/result-view/{anomaly_id}`
- `GET /api/v1/rca/run-status/{anomaly_id}`
- `POST /api/v1/feedback/confirm/{anomaly_id}`
- `POST /api/v1/feedback/reject/{anomaly_id}`
- `POST /api/v1/feedback/reject-all/{anomaly_id}`
- `POST /api/v1/feedback/rollback/{anomaly_id}`

## Email (account verification & password reset)

The API can send verification and password-reset messages via **SMTP** (e.g. **Gmail**, `EMAIL_PROVIDER=smtp`), **Resend** (`EMAIL_PROVIDER=resend`), or **log-only** local debugging (`EMAIL_PROVIDER=log`).

- **Where to put variables:** Copy `.env.example` to `.env` at the repository root and edit there. `api/main.py` loads `.env` with `python-dotenv`. For Docker, point `env_file` at `.env` or inject the same variables in the environment. **Do not commit `.env`, passwords, or API keys.**
- **Gmail SMTP (no custom domain):** Set `EMAIL_PROVIDER=smtp`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`, `SMTP_USERNAME` (full Gmail address), `SMTP_PASSWORD` (Google **App Password**, not your normal login password), `SMTP_FROM_EMAIL` (usually the same address), and `APP_BASE_URL` (your frontend, e.g. `http://localhost:5173`). The server uses **STARTTLS** on port 587 (not implicit SSL on 465).
- **Log vs real mail:** `EMAIL_PROVIDER=log` prints links to stdout/logs and sends nothing. Switch to `smtp` or `resend` for real delivery; see `.env.example`.
- **Testing locally:** With Postgres and the API running, call `POST /api/v1/users` (signup) and check your inbox (`smtp`/`resend`) or server logs (`log`). Confirm with `GET /api/v1/auth/verify-email?token=…` or your SPA. For reset: `POST /api/v1/auth/forgot-password`, then `POST /api/v1/auth/reset-password` with the token from email or logs.

Details: `api/email/settings.py`, `api/email/provider.py`, `api/services/auth_lifecycle.py`, `api/routers/auth_routes.py`.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Run RCA smoke checks:

```bash
python scripts/smoke_test_graph.py
python scripts/smoke_test_rca_api.py
```

## High-Level RCA Flow

1. Ingest anomaly + graph context
2. Run `pre_rca_gate`
3. Generate file candidates from trace frames
4. Compute deterministic signals
5. Rank candidates with weighted model
6. Persist evidence bundles first
7. Atomically write/supersede `RCA_ATTRIBUTED` edges
8. Accept/reject via feedback endpoints

## Repository Layout (Current Focus)

```text
log-analysis-AI-agent/
├── api/
├── artifacts/
├── evaluation/
├── feedback/
├── gates/
├── graph/
├── ingestion/
├── jobs/
├── machine_learning/
├── rca_engine/
├── scripts/
│   ├── smoke_test_graph.py
│   └── smoke_test_rca_api.py
├── old_log_arch_v1/   # archived legacy agent/jobs/utilities/tests/docs
└── README.md
```

## Legacy Archive

Legacy log-agent and RAG pipeline assets were moved under `old_log_arch_v1/`:

- `old_log_arch_v1/agent/`
- `old_log_arch_v1/utilities/`
- `old_log_arch_v1/code_testing/`
- `old_log_arch_v1/api/` (legacy jobs router/services/schemas/logging)
- `old_log_arch_v1/docs/`
- `old_log_arch_v1/scripts/`
- `old_log_arch_v1/legacy/`

