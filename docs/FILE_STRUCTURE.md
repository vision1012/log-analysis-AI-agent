# File Structure (RCA v2 First)

Concise map of the current repository with active RCA modules first.

## Active Core (Current)

| Path | Role |
|---|---|
| `graph/` | Neo4j client, writer, ontology/invariant docs, lifecycle docs |
| `rca_engine/` | Candidate generation, signal computation, ranking, RCA runner |
| `gates/` | Pre-ingestion and pre-RCA quality gates |
| `jobs/` | Locking and RCA job execution wrappers |
| `artifacts/` | Evidence store interface and implementations |
| `ingestion/` | Ingestion contracts and operational specs |
| `evaluation/` | RCA metrics and evaluation definitions |
| `feedback/` | Confirmation/rejection workflow specs |
| `api/main.py` | FastAPI app entrypoint |
| `api/core/` | Shared API path/config helpers |
| `api/middleware/` | Observability middleware |
| `api/routers/rca_routes.py` | RCA run/rerun/results endpoints |
| `api/routers/feedback_routes.py` | Feedback action endpoints |
| `api/routers/health.py` | Health endpoint |
| `api/services/rca_service.py` | RCA orchestration service |
| `api/services/feedback_service.py` | Feedback status transition service |
| `scripts/smoke_test_graph.py` | Graph-level RCA smoke test |
| `scripts/smoke_test_rca_api.py` | API-level RCA smoke test |

## Retained Supporting Areas

| Path | Role |
|---|---|
| `machine_learning/` | Kept in repo for anomaly-related ML work |
| `docs/` | Architecture, product, and operational docs |
| `data/`, `output/`, `runs/` | Runtime and experiment artifacts |

## Archived Legacy (Not Active Architecture)

All legacy log-agent, RAG, jobs pipeline, and utility-first assets are archived under:

- `old_log_arch_v1/agent/`
- `old_log_arch_v1/utilities/`
- `old_log_arch_v1/code_testing/`
- `old_log_arch_v1/api/`
- `old_log_arch_v1/scripts/`
- `old_log_arch_v1/docs/`
- `old_log_arch_v1/legacy/`
