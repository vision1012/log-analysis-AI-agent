# Graph-Based RCA v2 - Architecture Overview

This document describes the current active architecture for the graph-based RCA v2 platform.
Legacy log-agent/RAG architecture has been archived under `old_log_arch_v1/`.

## System Architecture

```text
Anomaly Ingestion
    |
    v
Graph Persistence (Neo4j)
  - Anomaly, StackFrame, File, Commit, Deployment
  - HAS_FRAME, IN_FILE, TOUCHED, DEPLOYED_COMMIT
    |
    v
Pre-RCA Gate (gates/pre_rca_gate.py)
  - accepted attribution protection
  - idempotency check
  - structural invariants
  - deployment quality degrade rules
    |
    v
RCA Engine (rca_engine/)
  - candidate generation
  - deterministic signal computation
  - weighted ranking
  - bundle-first evidence creation
  - atomic RCA_ATTRIBUTED writes
    |
    v
Feedback (feedback + API)
  - confirm/reject/reject-all/rollback
  - status transitions on RCA_ATTRIBUTED
    |
    v
Evaluation + Operations
  - metrics definitions (evaluation/)
  - smoke tests (scripts/)
```

## Active Runtime Components

### API Layer (`api/`)

- `api/main.py` boots FastAPI with health, RCA, and feedback routers.
- `api/routers/rca_routes.py` exposes manual run/rerun/results/run-status endpoints.
- `api/routers/feedback_routes.py` exposes confirm/reject/reject-all/rollback endpoints.
- `api/services/rca_service.py` orchestrates run execution and lock handling.
- `api/services/feedback_service.py` applies status transition operations.

### RCA Core (`rca_engine/`)

- `rca_runner.py` is the main orchestrator.
- `candidate_generator.py` derives file candidates from trace frames.
- `signal_computation.py` computes deterministic RCA signals.
- `ranking_model.py` scores and ranks candidates.
- Runner writes evidence bundles first, then atomically writes graph attributions.

### Graph + Storage

- `graph/neo4j_client.py` provides graph access.
- `graph/writer.py` performs idempotent upserts and atomic attribution writes.
- `artifacts/evidence_store.py` persists evidence bundles (local/in-memory implementations).

### Gate + Job Control

- `gates/pre_rca_gate.py` enforces pre-run invariants and degrade policy.
- `jobs/job_locking.py` and `jobs/rca_jobs.py` protect per-anomaly execution and background runs.

## RCA Data Model

Core nodes:

- `Anomaly`
- `StackFrame`
- `File`
- `Commit`
- `Deployment`

Core relationships:

- `HAS_FRAME`
- `IN_FILE`
- `TOUCHED`
- `DEPLOYED_COMMIT`
- `RCA_ATTRIBUTED`

`RCA_ATTRIBUTED` edges carry run metadata (`run_id`, confidence, method, status, `evidence_ref`, timestamps) and are updated by feedback flows.

## Execution Lifecycle

1. Pre-gate decides `pass`, `degrade`, or `block`.
2. Candidate files are generated from resolved/probable frames.
3. Signals are computed (frame depth, recency, deployment proximity, recurrence, etc.).
4. Candidates are ranked with deterministic weighted scoring.
5. Evidence bundles are created/persisted first.
6. Prior attributions are superseded and new `RCA_ATTRIBUTED` edges are written atomically.
7. Human/system feedback updates attribution statuses.

## Validation and Smoke Coverage

Use:

- `scripts/smoke_test_graph.py`
- `scripts/smoke_test_rca_api.py`

These scripts validate graph writes, RCA run flow, evidence linkage, and API-level behavior for active RCA modules.

## Legacy Archive

The previous log-agent and RAG/job pipeline implementation is intentionally archived in `old_log_arch_v1/`.
It is not part of the current RCA v2 execution path.
