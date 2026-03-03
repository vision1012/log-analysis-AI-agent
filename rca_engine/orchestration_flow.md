# RCA Orchestration Flow — End-to-End Pipeline

End-to-end flow for deterministic RCA v1: Pre-RCA gate, candidate generation, signal computation, ranking, writing candidate edges, writing evidence bundle, Post-RCA gate. Includes failure handling, retry logic, idempotency, and background job semantics.

---

## 1. End-to-End Flow

```
RCA run requested (anomaly scope)
        │
        ▼
┌───────────────────────┐
│  1. Pre-RCA Gate      │
└───────────────────────┘
        │
        ├── Block  → Exclude anomaly; skip; log
        ├── Degrade → Exclude deployments; proceed
        └── Pass   → Proceed
        │
        ▼
┌───────────────────────┐
│  2. Candidate         │
│     Generation       │
└───────────────────────┘
        │
        ├── No candidates → Skip write; done
        └── Candidates    → Proceed
        │
        ▼
┌───────────────────────┐
│  3. Signal            │
│     Computation       │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│  4. Ranking           │
└───────────────────────┘
        │
        ├── All below threshold → Skip write; done
        └── Top N qualify      → Proceed
        │
        ▼
┌───────────────────────┐
│  5. Post-RCA Gate     │
└───────────────────────┘
        │
        ├── Block  → Discard; no write
        └── Pass   → Proceed
        │
        ▼
┌───────────────────────┐
│  6. Write Candidate   │
│     Edges            │
└───────────────────────┘
        │
        ▼
┌───────────────────────┐
│  7. Write Evidence    │
│     Bundle            │
└───────────────────────┘
        │
        ▼
     Done
```

---

## 2. Step-by-Step

### Step 1: Pre-RCA Gate Check

| Action | Description |
|--------|-------------|
| **Input** | Anomaly IDs in run scope; deployments in correlation scope |
| **Checks** | I1, I2, I6, I8, I9, I12 (block); I10, I11, I13, I15 (degrade) |
| **Output** | Pass: proceed. Block: exclude anomaly; skip RCA. Degrade: exclude deployments; proceed with reduced correlation. |
| **Read-only** | Yes. No graph writes. |

### Step 2: Candidate Generation

| Action | Description |
|--------|-------------|
| **Input** | Anomaly (passed Pre-RCA) |
| **Traversal** | Anomaly → HAS_FRAME → StackFrame (frame_order < max_depth, resolution=resolved) → IN_FILE → File |
| **Exclusions** | Stdlib, vendor paths |
| **Cap** | K=5 candidates |
| **Output** | List of (File, representative_frame) pairs. Empty if no candidates. |

### Step 3: Signal Computation

| Action | Description |
|--------|-------------|
| **Input** | Each candidate (File, representative_frame) |
| **Computation** | 10 graph-derived signals per candidate. Traversals: File←TOUCHED←Commit; Deployment→DEPLOYED_COMMIT→Commit; prior RCA_ATTRIBUTED. |
| **Output** | signal_scores map per candidate. Missing-data fallbacks applied. |

### Step 4: Ranking

| Action | Description |
|--------|-------------|
| **Input** | Candidates with signal_scores |
| **Scoring** | Weighted sum; weight redistribution if signals unavailable; confidence cap if trace_completeness low |
| **Ranking** | Descending score; tie-breakers: frame_order, last_touch_recency, historical_recurrence, path |
| **Selection** | Top N=3 with score ≥ min_confidence |
| **Output** | Ordered list of up to 3 proposed attributions |

### Step 5: Post-RCA Gate

| Action | Description |
|--------|-------------|
| **Input** | Proposed attributions (in-memory) |
| **Checks** | I4 (target in trace), I8, I9 (no duplicate current), I16 (attributed_at present) |
| **Output** | Pass: proceed to write. Block: discard; no write. |
| **Read-only** | Validates proposed data; no graph read for I4 if Pre-RCA validated trace. |

### Step 6: Writing Candidate Edges

| Action | Description |
|--------|-------------|
| **Input** | Proposed attributions (Post-RCA pass) |
| **Pre-write** | Supersede prior RCA_ATTRIBUTED (status in {candidate, accepted}) for each anomaly |
| **Write** | Create up to 3 RCA_ATTRIBUTED edges per anomaly: Anomaly -[:RCA_ATTRIBUTED]-> StackFrame. Properties: run_id, method, confidence, status=candidate, evidence_ref, attributed_at |
| **Output** | Edges persisted in graph |

### Step 7: Writing Evidence Bundle

| Action | Description |
|--------|-------------|
| **Input** | Each RCA_ATTRIBUTED written; signal_scores; gate context (if Pre-RCA degraded) |
| **Write** | Create evidence bundle per attribution. bundle_id = evidence_ref. Store in artifact store or blob storage. |
| **Output** | Bundles persisted; graph holds evidence_ref only |

---

## 3. Failure Handling

### Per-Step Failure Behavior

| Step | Failure | Behavior |
|------|---------|----------|
| **Pre-RCA** | Gate blocks anomaly | Skip anomaly; process others in scope. Log excluded IDs. |
| **Pre-RCA** | Transient read error | Retry (see Retry Logic). |
| **Candidate generation** | No candidates | Skip write for anomaly; mark run partial success. |
| **Signal computation** | Graph read error | Retry. If persistent, fail run for that anomaly. |
| **Ranking** | All below threshold | Skip write; no failure. |
| **Post-RCA** | Gate blocks | Discard proposed; no write. Log reason. |
| **Write edges** | Graph write error | Retry. If persistent, fail run. Do not write partial. |
| **Write bundle** | Artifact store error | Retry. If persistent, optionally: write edges with evidence_ref=placeholder; backfill bundle later. Or fail run. |

### Partial Success

| Scenario | Behavior |
|----------|----------|
| **Batch of anomalies** | Some pass Pre-RCA; some block. Process passing; skip blocking. Run completes with partial results. |
| **One anomaly, no candidates** | No write. Run completes; anomaly has no new attribution. |
| **Write fails for one of three attributions** | All-or-nothing per anomaly: either all top-N written or none. No partial RCA_ATTRIBUTED for same anomaly. |

### Run State on Failure

| Failure point | Run state |
|---------------|-----------|
| Pre-RCA (all block) | completed (no attributions) |
| Candidate gen (no candidates) | completed (no attributions) |
| Post-RCA block | completed (no attributions) |
| Write error (transient) | retrying |
| Write error (persistent) | failed |

---

## 4. Retry Logic

### Retriable Failures

| Failure | Retry? | Max retries |
|---------|--------|-------------|
| Graph read timeout | Yes | 3 |
| Graph write timeout | Yes | 3 |
| Artifact store timeout | Yes | 3 |
| Transient network error | Yes | 3 |
| Pre-RCA invariant violation | No | — |
| Post-RCA invariant violation | No | — |
| No candidates | No | — |

### Retry Policy

| Aspect | Rule |
|--------|------|
| **Backoff** | Exponential: 1s, 2s, 4s (or configurable). |
| **Idempotency** | Retries must be idempotent. Same run_id; same proposed attributions. |
| **Supersede** | Before write, supersede prior. Retry may re-attempt supersede+write. Idempotent if prior already superseded. |
| **Bundle** | If edges written but bundle failed, retry bundle write only. Edges already have evidence_ref; bundle backfill. |

### Non-Retriable

| Condition | Action |
|-----------|--------|
| Pre-RCA block | Do not retry. Anomaly excluded. |
| Post-RCA block | Do not retry. Fix RCA logic or data. |
| Deterministic logic error | Do not retry. Fix and redeploy. |

---

## 5. Idempotency

### Run-Level Idempotency

| Scenario | Behavior |
|----------|----------|
| **Same idempotency key, prior run completed** | Return existing result; do not re-execute. |
| **Same idempotency key, prior run in progress** | Return in-progress; do not start duplicate. |
| **Same idempotency key, prior run failed** | Configurable: return failed or allow retry (new run_id). |
| **No idempotency key** | Every request is new run. |

### Write-Level Idempotency

| Scenario | Behavior |
|----------|----------|
| **Same run_id, same anomaly, re-write** | Supersede prior; write same top-N. Dedupe: if RCA_ATTRIBUTED (anomaly, run_id, frame) exists, skip create. |
| **Evidence bundle** | Same bundle_id (evidence_ref); overwrite or skip if exists. Idempotent. |

### Deterministic run_id

| Option | Behavior |
|--------|----------|
| **Derived** | run_id = hash(anomaly_id, window_id, rca_version). Same inputs → same run_id. Second run finds existing; returns cached. |
| **Assigned** | run_id = UUID/ULID. Idempotency via client-supplied key; run_id stored with key. |

---

## 6. Background Job Semantics

### Job Model

| Aspect | Description |
|--------|-------------|
| **Trigger** | Scheduled (e.g. hourly), event-driven (new anomalies), or on-demand. |
| **Scope** | One job processes one or more anomalies. |
| **Run** | One RCA run per job (or per anomaly, depending on design). run_id per run. |
| **State** | queued → running → completed | failed |

### Job Lifecycle

| State | Meaning |
|-------|---------|
| **queued** | Job created; not yet started |
| **running** | Pre-RCA through write in progress |
| **completed** | All anomalies processed; attributions written (or skipped per gate) |
| **failed** | Error; retries exhausted; or deterministic failure |

### Concurrency

| Scenario | Behavior |
|----------|----------|
| **Same anomaly, two jobs** | Lock anomaly; second job fails or queues. |
| **Different anomalies** | Process in parallel. |
| **Lock scope** | Per anomaly_id. Lock from run start until write complete or fail. |
| **Lock timeout** | Release after N minutes; job marked failed; anomaly unlocked. |

### At-Least-Once vs Exactly-Once

| Model | Behavior |
|-------|----------|
| **At-least-once** | Job may run twice (e.g. retry after timeout). Idempotent writes ensure no duplicates. Supersede + dedupe. |
| **Exactly-once** | Use idempotency key; skip if prior completed. Or: single consumer; no retry of completed job. |

### Job Output

| Output | When |
|--------|------|
| **Attributions written** | Post-RCA pass; edges and bundles persisted |
| **Run summary** | anomaly_ids processed; excluded; attributions per anomaly; failures |
| **Audit** | run_id, scope, timestamp, pass/fail, excluded IDs, gate outcomes |
