# Rerun Policy — Manual RCA Rerun Semantics

Defines when manual rerun is allowed or blocked, whether rerun overwrites or appends, and how old candidates are treated. Strong auditability. Simple state machine. No code.

---

## 1. When Manual Rerun Is Allowed

| Condition | Description | Rationale |
|-----------|-------------|-----------|
| **New data arrival** | Git sync added new commits (TOUCHED), new Files, or updated last-touch. Deployment backfill completed. Trace re-parsed with new resolution. | Graph state changed; rerun may produce different candidates. |
| **Parser version change** | Stacktrace parser upgraded; trace_ref or frame resolution may differ. | New parser may resolve previously unresolved frames; different candidate set. |
| **Deployment backfilled** | Deployment had backfill_status=pending; now has DEPLOYED_COMMIT. | Deploy signals (deploy_proximity, deploy_recency_rank) may now be non-zero. |
| **Human reject-all** | Human rejected all candidates from prior run. Anomaly has no accepted root cause. | User explicitly wants new suggestions; may trigger after graph update or to retry. |

### Trigger Semantics

| Trigger | Idempotency | Rerun allowed? |
|---------|-------------|----------------|
| **New data + new idempotency key** | New run. | Yes. |
| **New data + same idempotency key** | Configurable: return existing or allow rerun. For "new data" trigger, recommend new key to force rerun. | Yes, with new key. |
| **Human reject-all** | User-initiated. Typically new key or no key. | Yes. |
| **Parser version change** | New version implies new key (e.g. include parser_version in key). | Yes. |

---

## 2. When Rerun Is Blocked

| Condition | Description | Action |
|-----------|-------------|--------|
| **Still running** | An RCA run for this anomaly is in progress (locked). | Block. Return "anomaly in use" or queue. Do not start duplicate. |
| **Missing required data** | Pre-RCA gate would block: no HAS_FRAME, entire trace unresolved, invalid frame_order, missing timestamp. | Block. Return "anomaly not ready for RCA." Remediate data first. |
| **Same idempotency key, prior completed** | Idempotency: return existing result. | Block new execution. Return cached result. |

### Missing Required Data (Pre-RCA Blockers)

| Blocker | Meaning |
|---------|---------|
| I1 | Anomaly has no HAS_FRAME. No trace. |
| I2 | Entire trace unresolved. No frames with IN_FILE. |
| I6 | frame_order not unique (invalid). |
| I8, I9 | Duplicate RCA state (inconsistent; remediate first). |
| I12 | Anomaly missing timestamp. |

**Rule:** If Pre-RCA would block, do not enqueue or start rerun. Return error. User must remediate (e.g. re-ingest trace, fix data).

---

## 3. Overwrite vs Append: New run_id

### Policy: Append (New run_id)

| Rule | Description |
|------|-------------|
| **Rerun creates new run** | Each manual rerun (when allowed) is a new RCA run. New run_id. |
| **Does not overwrite** | New run does not overwrite old RCA_ATTRIBUTED edges. Old edges remain; their status is updated (see below). |
| **New edges created** | New run writes up to 3 new RCA_ATTRIBUTED edges with the new run_id. |

### Why Append

| Reason | Benefit |
|--------|---------|
| **Auditability** | Full history of runs. Each run_id traces to a specific execution. |
| **Evidence** | Evidence bundle per attribution; evidence_ref links to run. |
| **Evaluation** | Metrics can distinguish runs (e.g. first run vs rerun). |
| **Simple state machine** | No overwrite logic. Status transitions only. |

---

## 4. How Old Candidates Are Treated

### Before New Run Writes

| Old status | Action |
|------------|--------|
| **candidate** | Set to superseded. |
| **accepted** | Set to superseded. |
| **rejected** | No change. Rejected is terminal. |
| **superseded** | No change. Already superseded. |

### After New Run Writes

| Old attribution | New status | Meaning |
|-----------------|-----------|---------|
| Was candidate | superseded | Replaced by new run's candidates. No longer current. |
| Was accepted | superseded | Replaced by new run. Human's prior accept is superseded; new candidates are current. |
| Was rejected | rejected | Unchanged. Human said "not root cause"; that remains. |
| Was superseded | superseded | Unchanged. |

### Semantic: Keep but Inactive

| Treatment | Description |
|-----------|-------------|
| **Keep** | Old RCA_ATTRIBUTED edges are never deleted. They remain in the graph. |
| **Inactive** | superseded and rejected are "inactive" for current RCA. Only candidate and accepted are "current." |
| **Archived** | superseded and rejected serve as audit history. Query "current" by filtering status in {candidate, accepted}. |

### State Machine (Simple)

| Status | Current? | Terminal? | Rerun effect |
|--------|----------|-----------|--------------|
| candidate | Yes | No | → superseded |
| accepted | Yes | No | → superseded |
| rejected | No | Yes | Unchanged |
| superseded | No | Yes | Unchanged |

**Rule:** Rerun supersedes only candidate and accepted. Rejected and superseded are terminal; no further transitions.

---

## 5. Auditability

### What Is Preserved

| Data | Preserved |
|------|-----------|
| **All RCA_ATTRIBUTED edges** | Kept. Never deleted. Status may change (candidate/accepted → superseded). |
| **run_id** | Immutable on each edge. Links to specific run. |
| **evidence_ref** | Links to evidence bundle. Bundle contains signal_scores, timestamps. |
| **attributed_at** | When attribution was made. |
| **confidence** | Score at attribution time. Immutable. |

### Audit Queries

| Query | How |
|-------|-----|
| **Current candidates** | RCA_ATTRIBUTED where status in {candidate, accepted}. |
| **History of runs** | Group by run_id. Each run_id = one execution. |
| **Why was X superseded?** | New run wrote new candidates. Old run's attributions set to superseded. |
| **What did human reject?** | RCA_ATTRIBUTED where status=rejected. |

### No Deletion

| Rule | Edges are never deleted. Status transitions only. Rejected and superseded remain for audit. |
|------|-------------------------------------------------------------------------------------------|

---

## 6. Summary Table

| Aspect | Policy |
|--------|--------|
| **Rerun allowed** | New data, parser version change, deployment backfilled, human reject-all. Use new idempotency key to force rerun. |
| **Rerun blocked** | Still running (lock), missing required data (Pre-RCA block), same idempotency key + prior completed. |
| **Overwrite or append** | Append. New run_id. New RCA_ATTRIBUTED edges. |
| **Old candidates** | candidate, accepted → superseded. rejected, superseded → unchanged. All kept. |
| **Auditability** | No deletion. Full history. Status transitions only. |
