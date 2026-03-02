# Gate Integration — Quality Gates and Deterministic RCA

Specification for how post-ingestion, pre-RCA, and post-RCA quality gates integrate with deterministic RCA execution. Block vs degrade behavior, and what gets logged in the evidence bundle.

---

## 1. Execution Flow

```
Ingestion batch completes
        │
        ▼
┌───────────────────────┐
│  Post-Ingestion Gate  │
└───────────────────────┘
        │
        ├── Block  → Batch failed; entities not promoted; no RCA on this batch
        ├── Degrade → Batch marked degraded; entities promoted; RCA may run with lower confidence
        └── Pass   → Batch promoted; RCA eligible
        │
        │  (RCA run triggered separately: time window, job, or on-demand)
        │
        ▼
┌───────────────────────┐
│    Pre-RCA Gate       │  ← Per anomaly in scope
└───────────────────────┘
        │
        ├── Block  → Exclude anomaly from run; do not process
        ├── Degrade → Exclude some deployments; proceed with reduced correlation
        └── Pass   → Proceed to RCA
        │
        ▼
┌───────────────────────┐
│ Deterministic RCA v1  │  ← Candidate generation, scoring, selection
└───────────────────────┘
        │
        ├── No candidates / score < min_confidence → No attribution; log outcome
        └── Top candidate ≥ min_confidence → Propose attribution
        │
        ▼
┌───────────────────────┐
│   Post-RCA Gate       │  ← Validate proposed attribution(s)
└───────────────────────┘
        │
        ├── Block  → Do not write; discard proposed attribution
        └── Pass   → Write RCA_ATTRIBUTED; create evidence bundle
```

---

## 2. Post-Ingestion Gate

### When

After each ingestion batch commits to the graph. Triggered by batch completion.

### Relation to RCA

| Outcome | RCA Impact |
|---------|------------|
| **Block** | Batch not promoted. Anomalies in batch never become RCA-eligible. No RCA run will process them until batch is remediated and re-ingested. |
| **Degrade** | Batch promoted. Anomalies are RCA-eligible. RCA runs with degraded confidence (e.g. trace_completeness < 1, deploy signals = 0). |
| **Pass** | Batch promoted. Full confidence available for RCA. |

### Block vs Degrade

| Severity | Invariants | Action |
|----------|------------|--------|
| **Block** | I1, I2 (entire trace unresolved), I3, I6, I12, I13, I15 | Batch failed; entities not promoted; optional rollback |
| **Degrade** | I2 (partial trace), I5, I7, I19 | Log; apply remediation if possible; mark batch degraded; promote entities |
| **Warn** | I17, I18 | Log for cleanup; batch passes |

### What Gets Logged (Audit, Not Evidence Bundle)

| Logged | Content |
|--------|---------|
| Batch ID, timestamp, gate name | post_ingestion, pass/fail/degrade |
| Per-violation | invariant ID, entity IDs (anomaly_id, stack_frame_id, etc.), severity |
| Remediation | Attempts and outcomes |
| Retention | 90 days minimum |

**Note:** Post-ingestion gate runs before any RCA. No evidence bundle exists at this stage. Outcomes affect whether anomalies are RCA-eligible and with what baseline confidence.

---

## 3. Pre-RCA Gate

### When

Immediately before an RCA run starts for a given set of anomalies (scope: anomaly IDs or filter).

### Relation to RCA

| Outcome | RCA Impact |
|---------|------------|
| **Block** | Exclude violating anomalies from run. Do not execute deterministic RCA for them. Log excluded IDs. |
| **Degrade** | Exclude some deployments from correlation scope. Proceed with remaining anomalies; deploy signals = 0 or partial for affected anomalies. |
| **Pass** | All anomalies in scope proceed to deterministic RCA. |

### Block vs Degrade

| Severity | Invariants | Action |
|----------|------------|--------|
| **Block** | I1, I2 (entire trace unresolved), I6, I8, I9 | Exclude anomaly from run; do not process |
| **Degrade** | I10, I11 (service_ref or Deployment–Commit mismatch) | Exclude violating deployments from correlation; proceed with remaining; lower confidence |
| **Warn** | Missing service_ref (optional) | Log; proceed with reduced correlation scope |

### What Gets Logged (Audit, Not Evidence Bundle)

| Logged | Content |
|--------|---------|
| RCA run ID, scope, timestamp, gate name | pre_rca, pass/fail/degrade |
| Excluded anomaly IDs | Reason (invariant violated) |
| Correlation scope | Deployments, commits; any exclusions (e.g. deployment X excluded for I10) |
| Retention | 90 days minimum |

### Evidence Bundle: Gate Context

When an attribution is written (post-RCA pass), the evidence bundle **optionally** includes pre-RCA gate context:

| Field | Type | When Populated | Purpose |
|-------|------|----------------|---------|
| **gate_degradations** | array of string | Pre-RCA degraded | List of degradation codes, e.g. `["I10_deployment_excluded", "I11_commit_scope_mismatch"]` |
| **correlation_scope** | object | Optional | `{ deployments_in_scope: N, deployments_excluded: M, reason?: string }` |

**Rationale:** Explains why deploy signals may be 0 or low. Supports audit: "attribution had low deploy_proximity because deployment X was excluded for service_ref mismatch."

---

## 4. Post-RCA Gate

### When

Immediately before RCA_ATTRIBUTED edges are written. Validates proposed attribution(s) from the deterministic RCA run.

### Relation to RCA

| Outcome | RCA Impact |
|---------|------------|
| **Block** | Do not write proposed attribution. Discard. Log reason. No evidence bundle created. |
| **Pass** | Write RCA_ATTRIBUTED; create evidence bundle; persist. |

**Note:** Post-RCA gate has no degrade outcome; violations are blockers. Proposed data is in-memory; no graph read required for I4 if trace was validated at Pre-RCA.

### Block vs Degrade

| Severity | Invariants | Action |
|----------|------------|--------|
| **Block** | I4, I8, I9, I16 | Do not write; discard proposed attribution; log |
| **Degrade** | N/A | Not applicable |

### Block Scenarios

| Violation | Meaning | Action |
|-----------|---------|--------|
| **I4** | Proposed RCA_ATTRIBUTED target StackFrame not in Anomaly's trace | Discard; fix RCA logic |
| **I8** | Would create multiple RCA_ATTRIBUTED with status in {candidate, accepted} | Supersede prior; then write new; or discard if supersede fails |
| **I9** | Would create multiple accepted | Supersede prior; then write new; or discard |
| **I16** | Proposed attribution missing attributed_at | Reject; RCA must supply attributed_at |

### What Gets Logged (Audit)

| Logged | Content |
|--------|---------|
| RCA run ID, anomaly IDs, proposed details | Target frame, confidence, method |
| Per-attribution | pass/fail, invariant violated if failed |
| Discarded attributions | Reason (e.g. I4: target not in trace) |
| Retention | 90 days minimum |

### Evidence Bundle: When Created

| Condition | Evidence Bundle |
|----------|-----------------|
| Post-RCA **pass** | Created and persisted. evidence_ref on RCA_ATTRIBUTED = bundle_id. |
| Post-RCA **block** | Not created. No attribution written. |

---

## 5. Evidence Bundle: Gate-Related Fields

### Required (Always When Bundle Exists)

No gate-specific required fields. Standard fields apply (see evidence_bundle_contract.md).

### Optional (Gate Context)

| Field | Type | When | Purpose |
|-------|------|------|---------|
| **gate_degradations** | array of string | Pre-RCA had degrade | Codes for what was degraded: `I2_partial_trace`, `I10_deployment_excluded`, `I11_commit_scope_mismatch` |
| **trace_completeness_note** | string | Partial trace (I2) | e.g. "3/5 frames resolved" |
| **deployment_correlation_note** | string | Deployments excluded | e.g. "2 deployments excluded for service_ref mismatch" |

### Signal Scores and Gate Impact

| Gate Degradation | Signal(s) Affected | Evidence Bundle |
|------------------|--------------------|-----------------|
| I2 (partial trace) | trace_completeness < 1 | signal_scores.trace_completeness; optional trace_completeness_note |
| I10/I11 (deployment excluded) | deploy_proximity, deploy_recency_rank, deployment_timing_valid = 0 | signal_scores show 0; optional deployment_correlation_note; gate_degradations |
| Post-ingestion I19 (Commit without TOUCHED) | last_touch_recency = 0 for affected files | signal_scores.last_touch_recency |

**Rule:** signal_scores always reflect actual computed values. gate_degradations and notes explain *why* some signals are 0 or low. Supports audit and reproduction.

---

## 6. Block vs Degrade Summary

| Gate | Block | Degrade |
|------|-------|---------|
| **Post-ingestion** | Batch failed; entities not promoted; no RCA | Batch promoted; RCA runs with lower confidence; log violations |
| **Pre-RCA** | Exclude anomaly from run; do not process | Exclude deployments from correlation; proceed with remaining; log |
| **Post-RCA** | Discard proposed attribution; do not write | N/A (all violations block) |

### Block: What Happens

| Gate | Blocked Entity | RCA Execution |
|------|----------------|---------------|
| Post-ingestion | Entire batch | No RCA for any anomaly in batch |
| Pre-RCA | Individual anomaly | Skip that anomaly; process others in scope |
| Post-RCA | Proposed attribution | Do not write; anomaly has no new attribution |

### Degrade: What Happens

| Gate | Degraded | RCA Execution |
|------|----------|---------------|
| Post-ingestion | Batch (I2, I5, I7, I19) | RCA runs; trace_completeness, last_touch_recency, or deploy signals may be 0 or reduced |
| Pre-RCA | Correlation scope (I10, I11) | RCA runs; deploy signals = 0 for excluded deployments |
| Post-RCA | — | N/A |

---

## 7. Logging Summary

| Where | What |
|-------|------|
| **Audit log (all gates)** | Gate name, pass/fail/degrade, entity IDs, invariant violations, remediation attempts |
| **Evidence bundle (post-RCA pass only)** | signal_scores (always); gate_degradations, trace_completeness_note, deployment_correlation_note (optional, when applicable) |
| **No bundle (post-RCA block)** | Audit log only; no attribution; no evidence bundle |

---

## 8. Deterministic RCA Integration Checklist

| Step | Gate | Action on Block | Action on Degrade |
|------|------|----------------|-------------------|
| 1 | Post-ingestion | Batch not promoted; skip RCA for batch | Batch promoted; RCA may run with degraded signals |
| 2 | Pre-RCA | Exclude anomaly; skip RCA for it | Exclude deployments; proceed with deploy signals = 0 |
| 3 | Deterministic RCA | (Internal) No candidates → no proposed attribution | (Internal) Partial trace → trace_completeness < 1 |
| 4 | Post-RCA | Discard proposed; do not write | N/A |
| 5 | Write | — | Create RCA_ATTRIBUTED + evidence bundle (include gate_degradations if pre-RCA degraded) |
