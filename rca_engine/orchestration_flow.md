# RCA Orchestration Flow — Hybrid RCA Execution

Hybrid RCA execution: auto trigger when anomalies are ingested, manual trigger via API. Pre-RCA and Post-RCA gate enforcement, concurrency, retry policy, late data handling, evidence bundle timing, and observability.

**Locked decisions:** RCA attribution targets File; N_candidates=3, K_frames=5; never auto-supersede accepted; bundle-first atomicity; per-anomaly atomic write.

---

## 1. Attribution Target and Parameters

### RCA Attribution Targets File

| Rule | Description |
|------|-------------|
| **Primary target** | RCA attribution identifies a File as root cause. attributed_file_id is the canonical target. |
| **Evidence** | The representative StackFrame (smallest frame_order among frames pointing to that File) provides evidence. Evidence bundle stores attributed_file_id and attributed_frame_id. |
| **Output** | Up to N_candidates=3 Files per anomaly. Each attribution links Anomaly to the File (via representative StackFrame for graph traversal). |

### Parameters

| Parameter | Value | Purpose |
|-----------|-------|---------|
| **N_candidates** | 3 | Max RCA_ATTRIBUTED edges (candidates) written per anomaly. |
| **K_frames** | 5 | Max candidates scored. Cap before ranking. |

---

## 2. Hybrid Triggering

### Auto Trigger

| Trigger | When |
|---------|------|
| **Post-ingestion gate pass** | When a new Anomaly is ingested and passes the Post-ingestion gate, enqueue an RCA run for that anomaly. |

| Flow | Description |
|------|-------------|
| **Ingestion completes** | Anomaly + StackFrames + IN_FILE written to graph. |
| **Post-ingestion gate runs** | Validates I1, I2, I6, I12, etc. Pass or degrade. |
| **On pass** | Enqueue RCA run. Scope = anomaly_id. Job added to queue. |
| **On block** | Do not enqueue. Anomaly excluded from RCA. |
| **On degrade** | Enqueue. RCA runs with degraded confidence (e.g. deploy signals = 0). |

| Idempotency | Auto runs may use derived key (e.g. anomaly_id + window_id). Same anomaly + same window → one run. |

### Accepted Block: Never Auto-Supersede

| Rule | Description |
|------|-------------|
| **Block auto-run if accepted exists** | Before an auto-triggered RCA run executes (or at Pre-RCA), check: does this anomaly have an RCA_ATTRIBUTED with status=accepted? If yes, **block** the auto-run. Do not supersede. Do not write new candidates. |
| **No auto-supersede** | Auto-run never supersedes an accepted attribution. Human's confirmed root cause is preserved. |
| **Manual override** | Manual trigger may include override flag. When override=true, the run proceeds even if accepted exists. Supersedes prior (candidate or accepted). Use for explicit re-analysis. |

### Manual Trigger

| Trigger | When |
|---------|------|
| **API request** | Client calls API to trigger RCA run for a given anomaly_id. |

| Flow | Description |
|------|-------------|
| **Request** | anomaly_id, idempotency key (required for manual), optional override flag. |
| **Check accepted** | If anomaly has accepted attribution and override=false: block or warn. If override=true: proceed. |
| **Check idempotency** | Same key + prior run completed → return existing result. Same key + prior in progress → return in-progress. |
| **Enqueue** | If new run, add job to queue. Scope = anomaly_id. |
| **Process** | Worker picks up job; executes Pre-RCA through write. |

---

## 3. Pre-RCA Gate Enforcement

### When

Immediately before RCA execution starts (after job is dequeued, before candidate generation).

### Checks

| Invariant | Block | Degrade |
|-----------|-------|---------|
| I1 (no HAS_FRAME) | Yes | — |
| I2 (entire trace unresolved) | Yes | — |
| I6 (frame_order invalid) | Yes | — |
| I8, I9 (duplicate RCA) | Yes | — |
| I12 (no timestamp) | Yes | — |
| I10, I11 (deployment scope) | — | Yes |
| I13, I15 (missing timestamps) | — | Yes |

### Accepted Block (Auto-Run Only)

| Check | Action |
|-------|--------|
| **Anomaly has accepted attribution** | If trigger=auto and override not set: **Block**. Skip RCA. Do not supersede. Log: "accepted exists; auto-run blocked." |
| **Manual with override** | Proceed. Supersede prior (candidate or accepted) before write. |

### Enforcement

| Outcome | Action |
|---------|--------|
| **Block** | Exclude anomaly from run. Do not execute candidate generation. Log excluded anomaly_id and reason. Job completes; anomaly skipped. |
| **Degrade** | Exclude violating deployments from correlation. Proceed with RCA. Deploy signals = 0 or partial. Gate context logged for evidence bundle. |
| **Pass** | Proceed to candidate generation. |

### Per-Anomaly

Pre-RCA runs per anomaly in scope. Batch job: some anomalies may block; others proceed. Single-anomaly job: block = job completes with no attribution.

---

## 4. Concurrency Rules

### Per-Anomaly Lock

| Rule | Description |
|------|-------------|
| **Lock scope** | One lock per anomaly_id. |
| **Lock acquisition** | When job starts processing an anomaly (after dequeue, before Pre-RCA or at Pre-RCA start). |
| **Lock release** | When job completes (write done or failed) or lock timeout. |
| **Lock duration** | From start until write complete or failure. Timeout: e.g. 10 minutes. |

### Queue vs Reject

| Scenario | Behavior |
|----------|----------|
| **Same anomaly, job already running** | Second request: **Queue** — Add to queue. Job runs when first completes. Or **Reject** — Return 409 Conflict or "anomaly in use." Configurable. |
| **Same anomaly, job queued** | Second request: **Queue** — Dedupe by anomaly_id; one job per anomaly in queue. Or **Reject** — Return immediately. Configurable. |
| **Different anomalies** | Process in parallel. No conflict. |

### Recommended

| Mode | Use case |
|------|----------|
| **Queue** | Auto trigger; high volume. Avoid dropping work. |
| **Reject** | Manual trigger; user expects immediate feedback. Return "already running" or "queued." |

### Lock Timeout

| On timeout | Action |
|------------|--------|
| **Release lock** | Anomaly unlocked. Stuck job marked failed. |
| **Retry** | Optional: re-queue job. Or: do not retry; manual re-run required. |

---

## 5. Retry Policy

### Transient Failures

| Failure type | Retry? | Max retries | Backoff |
|--------------|--------|-------------|---------|
| Graph read timeout | Yes | 3 | Exponential: 1s, 2s, 4s |
| Graph write timeout | Yes | 3 | Same |
| Artifact store timeout | Yes | 3 | Same |
| Transient network error | Yes | 3 | Same |
| Queue/worker unavailable | Yes | 3 | Same |

| Behavior | Retry same job. Same run_id. Idempotent writes on success. |
|----------|------------------------------------------------------------|

### Permanent Failures

| Failure type | Retry? | Action |
|--------------|--------|--------|
| Pre-RCA block | No | Anomaly excluded. Job completed (no attribution). |
| Accepted block (auto-run) | No | Job completed. No write. Log "accepted exists." |
| Post-RCA block | No | Discard proposed. Job completed (no attribution). |
| No candidates | No | Job completed. No write. |
| Deterministic logic error | No | Fail job. Fix and redeploy. |
| Persistent graph/artifact error after retries | No | Fail job. Alert. Manual re-run when system healthy. |

### Retry Scope

| Scope | Rule |
|-------|------|
| **Per-step** | Retry the failing step (e.g. graph read). Do not restart from Pre-RCA unless graph state may have changed. |
| **Full re-run** | If lock timeout or worker crash, re-queue may start from Pre-RCA. Graph may have changed; new run. |

---

## 6. Late Data During a Run

### Scenario

New data arrives while an RCA run is in progress: late deployments, new commits (Git sync), updated frame resolution (trace re-parse).

### Policy

| Rule | Description |
|------|-------------|
| **Snapshot at Pre-RCA** | RCA uses graph state as of Pre-RCA (or job start). Data that arrives mid-run is not incorporated. |
| **Deterministic** | Same graph snapshot → same output. Run completes with consistent view. |
| **No mid-run refresh** | Do not re-read graph during signal computation. Use snapshot. |

### When Late Data Matters

| Data type | Effect if arrived during run |
|-----------|-----------------------------|
| **Late deployment** | Not seen. deploy_proximity, deploy_recency_rank = 0. Run completes. Manual re-run later will see it. |
| **New commits (TOUCHED)** | Not seen. last_touch_recency may be stale. Run completes. Re-run will use new commits. |
| **Updated frame resolution** | Not seen. trace_completeness, candidate set from old resolution. Run completes. Re-run will use new resolution. |

### After Run Completes

| Action | User can manual re-run with new idempotency key (or no key). New run sees updated graph. |
|--------|-----------------------------------------------------------------------------------------|
| **Auto re-trigger** | Optional: when deployment backfill completes or Git sync adds commits, enqueue RCA for affected anomalies. New run. |

### Recommendation

| Approach | Use snapshot at job start. Complete run with that snapshot. Late data → next run. Simple; deterministic. |
|----------|--------------------------------------------------------------------------------------------------------|

---

## 7. Evidence Bundle Creation Timing (Bundle-First Atomicity)

### Rule: Bundle Before Edges

| Rule | Description |
|------|-------------|
| **Evidence bundle must be created before writing RCA_ATTRIBUTED edges** | Create and persist evidence bundles first. Only then write edges. Edges reference bundle_id (evidence_ref); bundle must exist. |
| **Bundle-first atomicity** | No edge without a valid bundle. No orphan edges pointing to non-existent bundles. |

### Order of Operations

| Step | Action |
|------|--------|
| 1 | Post-RCA gate passes. Proposed attributions validated. |
| 2 | **Create evidence bundles.** One per proposed attribution (up to N_candidates=3). bundle_id = evidence_ref. |
| 3 | **Persist evidence bundles** to artifact store. All bundles for this anomaly must be persisted before any edge write. |
| 4 | **Write RCA_ATTRIBUTED edges** to graph. evidence_ref points to bundle_id. |
| 5 | **Release lock.** Done. |

### Failure Cases

| Case | Behavior |
|------|----------|
| **Bundle persist fails** | Retry. Do not write edges. If persistent failure after retries, fail job. No edges written. |
| **Bundles persisted, edge write fails** | Retry edge write. Bundles exist; idempotent. Orphan bundles if edge write permanently fails; cleanup or retain for audit. |
| **Partial bundle persist** | Do not write any edges. All-or-nothing for bundle persist per anomaly. |

---

## 8. Per-Anomaly Atomic Transaction Boundary

### Rule

| Rule | Description |
|------|-------------|
| **Per-anomaly atomic write** | All candidates (up to N_candidates=3) for one anomaly are written atomically. Either all are written or none. No partial writes. |

### Boundary

| Scope | One anomaly. One run. Up to 3 RCA_ATTRIBUTED edges. |
|-------|-----------------------------------------------------|
| **Atomic** | Supersede prior (if any) + write all new candidates in one atomic unit. |
| **No partial** | If write fails after 1 of 3 edges, rollback or compensate. Do not leave anomaly with partial state (e.g. 1 new candidate, 2 missing). |

### Implementation Note

| Mechanism | Use transaction (graph + artifact store if supported), or: write all edges in one batch; if any fails, fail entire batch; retry. No single-edge commits. |
|-----------|------------------------------------------------------------------------------------------------------------------------------------------------------------|

---

## 9. Post-RCA Gate Enforcement

### When

Immediately before evidence bundles are created and RCA_ATTRIBUTED edges are written. After ranking and selection. Validates proposed attributions in memory.

### Checks

| Invariant | Check | Action on failure |
|-----------|-------|------------------|
| I4 | Target (File via representative StackFrame) in Anomaly's trace (HAS_FRAME) | Discard proposed attribution. Do not write. |
| I8 | Would not create multiple current (candidate/accepted) per anomaly | Supersede prior (manual override only); then write. If supersede fails, discard. |
| I9 | Would not create multiple accepted | Supersede prior (manual override only); then write. If supersede fails, discard. |
| I16 | attributed_at present | Reject. Do not write. |

### Enforcement

| Outcome | Action |
|---------|--------|
| **Pass** | Proceed to create bundles, then write edges. |
| **Block** | Discard proposed attribution(s). Do not create bundles. Do not write edges. Log reason. Job completes; anomaly has no new attribution. |

### No Degrade

Post-RCA has no degrade outcome. All violations block.

---

## 10. Observability

### Logs Required

| Event | Log fields |
|-------|------------|
| **RCA run started** | run_id, anomaly_id, trigger (auto|manual), idempotency_key, override, timestamp |
| **Accepted block** | run_id, anomaly_id, reason="accepted exists", trigger=auto |
| **Pre-RCA result** | run_id, anomaly_id, pass|block|degrade, excluded_anomaly_ids, excluded_deployment_ids, reason |
| **Candidate count** | run_id, anomaly_id, candidate_count, excluded_count |
| **Post-RCA result** | run_id, anomaly_id, pass|block, discarded_reason if block |
| **Bundles persisted** | run_id, anomaly_id, bundle_ids |
| **Edges written** | run_id, anomaly_id, attribution_count, evidence_refs |
| **Run completed** | run_id, anomaly_id, status (completed|failed), duration_ms |
| **Run failed** | run_id, anomaly_id, error, failure_step, retry_count |
| **Lock acquired/released** | anomaly_id, lock_id, acquired|released, timestamp |

### Metrics Required

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| **rca_runs_total** | Counter | trigger, status | Run count by trigger and outcome |
| **rca_run_duration_seconds** | Histogram | trigger, status | Run latency |
| **rca_candidates_per_run** | Histogram | — | Candidate count distribution |
| **rca_attributions_written** | Counter | — | Attributions written |
| **rca_accepted_blocks** | Counter | — | Auto-runs blocked by accepted |
| **rca_pre_rca_blocks** | Counter | reason | Pre-RCA blocks by reason |
| **rca_post_rca_blocks** | Counter | reason | Post-RCA blocks by reason |
| **rca_queue_depth** | Gauge | — | Jobs in queue |
| **rca_lock_hold_duration_seconds** | Histogram | — | Lock hold time |
| **rca_retries_total** | Counter | step, failure_type | Retry count |

### Traces Required

| Span | Attributes |
|------|------------|
| **rca_run** | run_id, anomaly_id, trigger |
| **pre_rca_gate** | run_id, result |
| **candidate_generation** | run_id, candidate_count |
| **signal_computation** | run_id, candidate_count |
| **ranking** | run_id |
| **post_rca_gate** | run_id, result |
| **write_bundles** | run_id, bundle_count |
| **write_edges** | run_id, attribution_count |

| Propagation | Trace ID propagated across queue, worker, and storage. |

### Retention

| Data | Retention |
|------|-----------|
| Logs | 90 days minimum |
| Metrics | 90 days (aggregated); 30 days (raw) |
| Traces | 7–30 days |

---

## 11. End-to-End Flow Summary

```
Auto: Anomaly ingested → Post-ingestion pass → Enqueue RCA
Manual: API request (anomaly_id, idempotency_key, override?) → Check idempotency → Enqueue or return existing

      │
      ▼
Dequeue job → Acquire per-anomaly lock (or queue/reject)
      │
      ▼
Pre-RCA gate → Block: skip. Degrade: exclude deployments. Pass: proceed.
      │
      ├── [Auto] Accepted exists? → Block. Release lock. Done.
      └── [Manual] Override? → If no override and accepted exists: block. Else proceed.
      │
      ▼
Candidate generation (K_frames=5) → Signal computation → Ranking → Top N_candidates=3
      │
      ├── No candidates / below threshold → Release lock; done
      └── Top N qualify
      │
      ▼
Post-RCA gate → Block: discard. Pass: proceed.
      │
      ▼
Create evidence bundles → Persist bundles (bundle-first)
      │
      ▼
Write RCA_ATTRIBUTED edges (per-anomaly atomic transaction)
      │
      ▼
Release lock → Done
```
