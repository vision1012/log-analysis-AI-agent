# RCA and Feedback API Reference (Current)

This document describes the active API for the graph-based RCA platform.

## Base Runtime

- App entry: `api/main.py`
- Active routers: `health`, `rca_routes`, `feedback_routes`

## Health Endpoint

### `GET /health`

Response:

```json
{ "status": "ok" }
```

## RCA Endpoints

### `POST /api/v1/rca/run/{anomaly_id}`

Trigger a manual RCA run.

Request:

```json
{ "idempotency_key": "string" }
```

### `POST /api/v1/rca/rerun/{anomaly_id}`

Trigger an RCA rerun (force mode).

Request:

```json
{ "idempotency_key": "string" }
```

### `GET /api/v1/rca/results/{anomaly_id}`

Return candidate list for the anomaly.

### `GET /api/v1/rca/result-view/{anomaly_id}`

Return structured RCA result view (accepted/candidate state).

### `GET /api/v1/rca/run-status/{anomaly_id}`

Return lock/run status for the anomaly.

## Feedback Endpoints

### `POST /api/v1/feedback/confirm/{anomaly_id}`

Confirm one candidate and reject others.

Request:

```json
{
  "file_id": "string",
  "run_id": "string",
  "actor_id": "string",
  "reason": "optional"
}
```

### `POST /api/v1/feedback/reject/{anomaly_id}`

Reject one candidate.

### `POST /api/v1/feedback/reject-all/{anomaly_id}`

Reject all candidates for an anomaly.

Request:

```json
{ "actor_id": "string", "reason": "optional" }
```

### `POST /api/v1/feedback/rollback/{anomaly_id}`

Rollback accepted attribution to rejected.

## Legacy Note

Legacy utility-style `run_*` API and jobs pipeline docs are archived in `old_log_arch_v1/docs/`.
