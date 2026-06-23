# Development Setup

Minimal guide for running Neo4j locally and required environment variables.

---

## Neo4j with Docker

### Start Neo4j

```bash
docker run -d \
  --name neo4j-rca \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your-password \
  neo4j:5
```

- **7474**: HTTP (browser UI)
- **7687**: Bolt (driver connection)

### Stop and Remove

```bash
docker stop neo4j-rca
docker rm neo4j-rca
```

### Run Migrations

```bash
# After setting NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
python -m graph.migrations
```

---

## Required Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEO4J_URI` | Yes | — | Bolt URI, e.g. `bolt://localhost:7687` |
| `NEO4J_USER` | Yes | — | Neo4j username (e.g. `neo4j`) |
| `NEO4J_PASSWORD` | Yes | — | Neo4j password |

### Example `.env`

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-password
```

---

## Optional: Artifact Store

For evidence bundle persistence (future):

| Variable | Description |
|----------|-------------|
| `EVIDENCE_STORE_URI` | Artifact store endpoint (S3, local path, etc.) |
| `EVIDENCE_STORE_BUCKET` | Bucket or prefix for bundles |

---

## Dependencies

For graph migrations and RCA:

```bash
pip install -r requirements.txt
```

## Verify JIRA-first RCA locally

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
python scripts/smoke_test_graph.py
python scripts/smoke_test_graphrag.py
# With API running:
python scripts/smoke_test_rca_api.py
```

---

## End-to-End MCP RCA Validation

Validate the full MCP-powered RCA pipeline without frontend changes.

### What it checks

1. API health (`GET /health`)
2. MCP status (`GET /api/v1/mcp/status`) and enabled providers
3. MCP context preview (`POST /api/v1/mcp/context/preview`) — `UnifiedInvestigationContext` fields
4. JIRA RCA orchestration (`POST /api/v1/jira/rca/run`)
5. RCA candidates in the response
6. Confidence assessments (`confidence_assessment` on candidates or `confidence_assessments` on run)
7. GraphRAG explanation (`explanation_payload`)
8. Investigation narrative (via `GET /api/v1/rca/explanation/{anomaly_id}` when available)
9. Neo4j investigation graph persistence (graceful skip if disabled)
10. Evidence bundle on disk (when `EVIDENCE_STORE_DIR` is set)

Terminal output uses `[PASS]`, `[FAIL]`, and `[SKIPPED]` per step.

### Mock mode (no external MCP credentials)

```bash
# Terminal 1 — API
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — seed auth user (once)
export POSTGRES_URL=postgresql://...
python scripts/seed_users.py

# Neo4j for graph RCA + confidence (recommended)
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=your-password
python -m graph.migrations

# Run validation (embedded ticket + sample logs; MCP preview uses enabled_sources=[])
python scripts/validate_e2e_mcp_rca_flow.py --mode mock
```

Optional auth override:

```bash
export API_BEARER_TOKEN=<jwt>
# or VALIDATE_AUTH_EMAIL / VALIDATE_AUTH_PASSWORD (default: seed user)
```

### Live mode (real `.env` credentials on API host)

```bash
python scripts/validate_e2e_mcp_rca_flow.py \
  --mode live \
  --ticket-key PROJ-123 \
  --service-name auth-service \
  --repo-name org/auth-service \
  --logs-file scripts/fixtures/e2e_mcp_rca_sample.log
```

Providers without credentials on the **validator host** are reported as `[SKIPPED]` (e.g. `Live credentials: datadog`). The API still runs with its own `.env`; use MCP status output to confirm provider health.

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--base-url` | `http://127.0.0.1:8000` | API base URL |
| `--mode` | `mock` | `mock` or `live` |
| `--ticket-key` | `MOCK-1001` | Jira ticket key |
| `--service-name` | `auth-service` | Service for hints / graph seed |
| `--repo-name` | `org/auth-service` | Repo name for graph seed |
| `--logs-file` | `scripts/fixtures/e2e_mcp_rca_sample.log` | Log upload content |
| `--anomaly-id` | auto-generated | Anomaly id for graph RCA |
| `--no-bootstrap-anomaly` | — | Skip Neo4j anomaly seeding |

Exit code `0` when all required checks pass; `1` when any check fails.

