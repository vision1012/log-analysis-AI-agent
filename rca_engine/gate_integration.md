# Gate Integration — Pre-RCA and Post-RCA Quality Gates

How quality gates apply before and after RCA runs. What blocks execution vs what degrades confidence, and exactly what gets logged to the evidence bundle.

---

## 1. Gate Placement

| Gate | When | Scope |
|------|------|-------|
| **Pre-RCA** | Immediately before an RCA run starts | Anomalies in run scope; deployments in correlation scope |
| **Post-RCA** | Immediately before RCA_ATTRIBUTED edges are written | Proposed attribution(s) from the RCA run |

---

## 2. Pre-RCA Gate

### Purpose

Ensure anomalies are processable before deterministic RCA executes. Validate correlation scope (deployments, commits) for timing signals.

### Block vs Degrade

| Outcome | Meaning | RCA Execution |
|---------|---------|---------------|
| **Block** | Anomaly fails a blocker invariant | Do not run RCA for that anomaly. Skip entirely. Log excluded anomaly IDs. |
| **Degrade** | Correlation scope has issues; not fatal | Run RCA. Exclude violating deployments from correlation. Deploy signals = 0 or partial. Lower confidence. |
| **Pass** | All checks pass | Run RCA with full correlation scope. |

### What Blocks Execution

| Invariant | Check | Action |
|-----------|-------|--------|
| **I1** | Anomaly has no HAS_FRAME | Exclude anomaly; do not process |
| **I2** | Entire trace unresolved (all frames lack IN_FILE) | Exclude anomaly; do not process |
| **I6** | frame_order not unique per Anomaly | Exclude anomaly; do not process |
| **I8** | Multiple RCA_ATTRIBUTED with status in {candidate, accepted} | Exclude anomaly; do not process |
| **I9** | Multiple RCA_ATTRIBUTED with status=accepted | Exclude anomaly; do not process |
| **I12** | Anomaly missing timestamp | Exclude anomaly; do not process |

### What Degrades Confidence

| Invariant | Check | Action |
|-----------|-------|--------|
| **I10** | service_ref mismatch between Anomaly and Deployment | Exclude that deployment from correlation; proceed with remaining |
| **I11** | Deployment–Commit scope mismatch (wrong service) | Exclude that deployment from correlation; proceed with remaining |
| **I13, I15** | Deployment or Commit missing timestamp (in correlation scope) | Exclude from correlation; proceed |

**Effect:** Degradation excludes deployments from correlation. Deploy signals (deploy_proximity, deploy_recency_rank, deployment_timing_valid) become 0 or partial for affected anomalies. RCA still runs; confidence is lower.

### Audit Logging (Not Evidence Bundle)

| Logged | Content |
|--------|---------|
| RCA run ID, scope, timestamp | pre_rca, pass/fail/degrade |
| Excluded anomaly IDs | Reason (invariant violated) |
| Excluded deployment IDs | Reason (I10, I11). |
| Retention | 90 days minimum |

---

## 3. Post-RCA Gate

### Purpose

Validate proposed attribution(s) before writing to the graph. Ensure RCA_ATTRIBUTED targets are valid and invariants are preserved.

### Block vs Degrade

| Outcome | Meaning | RCA Execution |
|---------|---------|---------------|
| **Block** | Proposed attribution violates invariants | Do not write. Discard proposed attribution. No evidence bundle created. |
| **Degrade** | N/A | Post-RCA has no degrade outcome. All violations block. |
| **Pass** | All checks pass | Write RCA_ATTRIBUTED; create evidence bundle; persist. |

### What Blocks Execution

| Invariant | Check | Action |
|-----------|-------|--------|
| **I4** | Proposed RCA_ATTRIBUTED target StackFrame not in Anomaly's trace (no HAS_FRAME) | Discard proposed attribution; do not write |
| **I8** | Would create multiple RCA_ATTRIBUTED with status in {candidate, accepted} per Anomaly | Supersede prior; then write new. If supersede fails, discard. |
| **I9** | Would create multiple accepted per Anomaly | Supersede prior; then write new. If supersede fails, discard. |
| **I16** | Proposed attribution missing attributed_at | Reject; do not write |

**Note:** Post-RCA validates in-memory proposed data. No graph read required for I4 if trace was validated at Pre-RCA.

### Audit Logging (Not Evidence Bundle)

| Logged | Content |
|--------|---------|
| RCA run ID, anomaly IDs, proposed details | Target frame, confidence, method |
| Per-attribution | pass/fail, invariant violated if failed |
| Discarded attributions | Reason (e.g. I4: target not in trace) |
| Retention | 90 days minimum |

---

## 4. Exactly What Gets Logged to the Evidence Bundle

The evidence bundle is created only when Post-RCA passes and attribution is written. No bundle exists when Post-RCA blocks.

### Always Logged (When Bundle Exists)

| Field | Source | Purpose |
|-------|--------|---------|
| **signal_scores** | Map of 10 signal names → values (0–1) | Required for reproduction. Reflects actual computed values. gate_degradations explain why some are 0. |

All other standard fields (bundle_id, anomaly_id, trace_ref, attributed_file_id, etc.) are populated per evidence_bundle_contract.md and evidence_bundle_mapping.md.

### Conditionally Logged (Gate Context)

| Field | When Populated | Exact Content |
|-------|----------------|---------------|
| **gate_degradations** | Pre-RCA had degrade | Array of strings. Codes: `I10_deployment_excluded`, `I11_commit_scope_mismatch`. One entry per degradation type that occurred. |
| **trace_completeness_note** | Partial trace (I2 from post-ingestion or earlier) | String. Format: `"N/M frames resolved"` where N = resolved count, M = total. Example: `"3/5 frames resolved"`. |
| **deployment_correlation_note** | Pre-RCA: deployments excluded (I10, I11) | String. Format: `"N deployments excluded for <reason>"`. Example: `"2 deployments excluded for service_ref mismatch"`. |

### When Each Optional Field Is Populated

| Condition | gate_degradations | trace_completeness_note | deployment_correlation_note |
|-----------|-------------------|-------------------------|----------------------------|
| Pre-RCA pass | Omit | Omit if trace complete | Omit |
| Pre-RCA degrade (I10/I11) | Include `I10_deployment_excluded` and/or `I11_commit_scope_mismatch` | Omit if trace complete | Include |
| Partial trace (I2) | Include `I2_partial_trace` if from pre-RCA context | Include | Omit unless also degraded |

**Rule:** signal_scores always reflect computed values. gate_degradations and notes explain *why* some signals are 0 or low. Supports audit and reproduction.

### When No Evidence Bundle Is Created

| Condition | Evidence Bundle |
|-----------|-----------------|
| Pre-RCA block | Anomaly excluded; no RCA run; no bundle |
| Post-RCA block | Proposed attribution discarded; no write; no bundle |
| RCA produces no candidates | No proposed attribution; no bundle |
| All candidates below min_confidence | No proposed attribution; no bundle |

---

## 5. Block vs Degrade Summary

| Gate | Block | Degrade |
|------|-------|---------|
| **Pre-RCA** | Exclude anomaly; do not run RCA | Exclude deployments; run RCA with deploy signals = 0 |
| **Post-RCA** | Discard proposed attribution; do not write | N/A |

### Block: What Happens

| Gate | Blocked Entity | Result |
|------|----------------|--------|
| Pre-RCA | Individual anomaly | Skip that anomaly; process others in scope. No RCA for blocked anomaly. No evidence bundle. |
| Post-RCA | Proposed attribution | Do not write; anomaly has no new attribution. No evidence bundle. |

### Degrade: What Happens

| Gate | Degraded | Result |
|------|----------|--------|
| Pre-RCA | Correlation scope (I10, I11) | RCA runs; deploy signals = 0 for excluded deployments. Evidence bundle includes gate_degradations and deployment_correlation_note when attribution is written. |
| Post-RCA | — | N/A |

---

## 6. Flow Summary

```
RCA run starts
      │
      ▼
┌─────────────────┐
│   Pre-RCA Gate  │
└─────────────────┘
      │
      ├── Block  → Exclude anomaly; skip RCA; no bundle
      ├── Degrade → Exclude deployments; run RCA; bundle includes gate_degradations, deployment_correlation_note
      └── Pass   → Run RCA; bundle has no gate_degradations
      │
      ▼
┌─────────────────┐
│ Deterministic   │
│ RCA v1          │
└─────────────────┘
      │
      ├── No candidates / below threshold → No bundle
      └── Proposals produced
      │
      ▼
┌─────────────────┐
│  Post-RCA Gate  │
└─────────────────┘
      │
      ├── Block  → Discard; no write; no bundle
      └── Pass   → Write RCA_ATTRIBUTED; create evidence bundle
```
