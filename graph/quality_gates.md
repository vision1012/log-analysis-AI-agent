# Quality Gates — Invariant Enforcement

When and how invariants are enforced in the RCA pipeline. Production-oriented.

---

## Gate Overview

| Gate | Trigger | Purpose |
|------|---------|---------|
| Post-ingestion | After each ingestion batch commits to graph | Validate structural integrity of new data |
| Pre-RCA | Before RCA run starts for an anomaly set | Ensure anomalies are processable |
| Post-RCA | Before RCA_ATTRIBUTED edges are written | Validate attribution before persistence |
| Pre-patch | Before any patch/update to existing nodes or edges | Prevent invariant violations from corrections |

---

## 1. Post-Ingestion Gate

### When

Runs after each ingestion batch commits writes to the graph. Triggered by ingestion completion (batch ID or job ID).

### Checks Run

| Invariant | Check |
|-----------|-------|
| I1 | Every Anomaly in batch has at least one HAS_FRAME |
| I2 | Every StackFrame with resolution=resolved has IN_FILE; entire trace unresolved = block |
| I3 | Every Deployment in batch has exactly one DEPLOYED_COMMIT |
| I5 | No duplicate TOUCHED per (Commit, File) in batch |
| I6 | frame_order unique per Anomaly in batch |
| I7 | frame_order contiguous (0 to n−1) per Anomaly |
| I12 | Every Anomaly has timestamp |
| I13 | Every Deployment has timestamp |
| I15 | Every Commit has timestamp |
| I17 | No StackFrame in batch is orphan (has incoming HAS_FRAME) |
| I18 | No File in batch is orphan (has IN_FILE or TOUCHED) |
| I19 | Every Commit in batch has at least one TOUCHED |

### Pass/Fail Criteria

- **Pass:** No blocker violations; degrade and warn violations logged but do not fail the gate.
- **Fail:** Any blocker (I1, I2 when entire trace unresolved, I3, I6, I12, I13, I15) violated for entities in the batch.

### Blocked vs Degrade

| Outcome | Action |
|---------|--------|
| **Blocked** | Batch marked failed; entities not promoted to "ingested" state; optional rollback of batch writes. |
| **Degrade** | I2 (partial trace), I5, I7, I19 violations: log, apply remediation if possible, mark batch degraded. RCA may run with lower confidence. |
| **Warn** | I17, I18: log for cleanup; batch passes. |

### Audit Logging

- Batch ID, timestamp, gate name, pass/fail.
- Per-violation: invariant ID, entity IDs (anomaly_id, stack_frame_id, etc.), severity.
- Remediation attempts and outcomes.
- Retention: align with compliance; recommend 90 days minimum.

### Retry / Idempotency

- Gate is read-only; no writes. Safe to re-run.
- Idempotent: same batch ID yields same result.
- Retry: if gate fails due to transient read issue, retry up to N times with backoff.
- If violations persist: fail batch, alert, do not auto-retry ingestion.

---

## 2. Pre-RCA Gate

### When

Runs immediately before an RCA run starts for a given set of anomalies (e.g., anomalies in a time window or job).

### Checks Run

| Invariant | Check |
|-----------|-------|
| I1 | Every Anomaly in scope has at least one HAS_FRAME |
| I2 | StackFrames with resolution=resolved have IN_FILE; exclude anomalies with entire trace unresolved |
| I6 | frame_order unique per Anomaly in scope |
| I8 | No Anomaly in scope has multiple RCA_ATTRIBUTED with status in {candidate, accepted} |
| I9 | No Anomaly in scope has multiple RCA_ATTRIBUTED with status=accepted |
| I10 | service_ref present and consistent for Anomaly and Deployment when correlating |
| I11 | Deployment–Commit scope matches service |
| I12 | Every Anomaly in scope has timestamp |
| I13 | Every Deployment in correlation scope has timestamp |
| I15 | Every Commit in correlation scope has timestamp |

### Pass/Fail Criteria

- **Pass:** All anomalies in scope satisfy I1, I2, I6, I12; no I8 or I9 violations; service and timestamp checks pass for correlation scope.
- **Fail:** Any anomaly lacks frames (I1), has entire trace unresolved (I2), has invalid frame_order (I6), or has duplicate accepted RCA (I8, I9).

### Blocked vs Degrade

| Outcome | Action |
|---------|--------|
| **Blocked** | Exclude violating anomalies from RCA run; do not process. Log and alert. |
| **Degrade** | I10/I11 inconsistency for some deployments: exclude those deployments from correlation; proceed with remaining. Lower confidence for affected anomalies. |
| **Warn** | Missing service_ref where optional: log; proceed with reduced correlation scope. |

### Audit Logging

- RCA run ID, scope (anomaly IDs or filter), timestamp, gate name, pass/fail.
- Excluded anomaly IDs and reason (invariant violated).
- Correlation scope (deployments, commits) and any exclusions.
- Retention: align with RCA run retention; recommend 90 days minimum.

### Retry / Idempotency

- Gate is read-only. Safe to re-run.
- Idempotent for same scope and graph state.
- Retry: if transient read failure, retry up to N times. Do not retry if violations are deterministic (e.g., missing edges).
- If gate fails: skip RCA for violating anomalies; optionally retry gate after remediation (e.g., backfill).

---

## 3. Post-RCA Gate

### When

Runs immediately before RCA_ATTRIBUTED edges are written to the graph. Validates the proposed attribution(s) from the RCA run.

### Checks Run

| Invariant | Check |
|-----------|-------|
| I4 | Every proposed RCA_ATTRIBUTED target StackFrame has HAS_FRAME from same Anomaly |
| I8 | Proposed attribution would not create multiple RCA_ATTRIBUTED with status in {candidate, accepted} per Anomaly |
| I9 | Proposed attribution would not create multiple accepted per Anomaly |
| I16 | Every proposed RCA_ATTRIBUTED has attributed_at |

### Pass/Fail Criteria

- **Pass:** All proposed attributions satisfy I4, I8, I9, I16.
- **Fail:** Any proposed attribution violates I4 (target not in trace), I8, I9, or I16.

### Blocked vs Degrade

| Outcome | Action |
|---------|--------|
| **Blocked** | Do not write violating attribution(s). Log and discard. Optionally set existing to superseded if new attribution is valid but would violate I8/I9 (i.e., write new, set old status=superseded). |
| **Degrade** | N/A for this gate; violations are blockers. |

### Audit Logging

- RCA run ID, anomaly IDs, proposed attribution details (target frame, confidence, method).
- Per-attribution: pass/fail, invariant violated if failed.
- Discarded attributions and reason.
- Retention: align with RCA audit; recommend 90 days minimum.

### Retry / Idempotency

- Gate validates in-memory proposed data; no graph read required for I4 if trace is already validated at Pre-RCA.
- Idempotent for same proposed attributions.
- Retry: if validation logic fails transiently, retry. If I4 fails (target not in trace), do not retry; fix RCA logic.
- If gate fails: do not write; optionally re-run RCA with corrected logic.

---

## 4. Pre-Patch Gate

### When

Runs before any patch or update to existing nodes or edges (e.g., backfill, correction, superseding RCA). Only active when patching is enabled.

### Checks Run

| Invariant | Check |
|-----------|-------|
| I1–I3 | Patch does not create Anomaly without HAS_FRAME, Deployment without DEPLOYED_COMMIT; StackFrame without IN_FILE allowed when resolution=unknown |
| I4 | Patch does not create RCA_ATTRIBUTED with target not in trace |
| I5 | Patch does not create duplicate TOUCHED |
| I6–I7 | Patch does not create invalid or non-contiguous frame_order |
| I8–I9 | Patch does not create duplicate RCA_ATTRIBUTED with status in {candidate, accepted} or duplicate accepted |
| I10–I11 | Patch does not create service_ref inconsistency |
| I12–I16 | Patch does not remove or invalidate required timestamps |
| I17–I19 | Patch does not create new orphans (or removes orphans as intended) |

Scope: only entities and relationships touched by the patch.

### Pass/Fail Criteria

- **Pass:** Patch would not violate any invariant for affected entities.
- **Fail:** Patch would violate any blocker invariant.

### Blocked vs Degrade

| Outcome | Action |
|---------|--------|
| **Blocked** | Reject patch; do not apply. Log and alert. |
| **Degrade** | Degrade-level violations (I5, I7, I19): apply remediation as part of patch if possible; otherwise reject. |
| **Warn** | Orphan creation (I17, I18): log; allow if patch explicitly creates orphans for later cleanup. |

### Audit Logging

- Patch ID, timestamp, gate name, pass/fail.
- Patch description (what is being changed, why).
- Per-entity: before/after state for affected nodes and edges.
- Violations and remediation attempts.
- Retention: align with change audit; recommend 1 year for patches.

### Retry / Idempotency

- Gate validates proposed patch against current graph state.
- Idempotent for same patch and graph state. If graph changes between validation and apply, re-run gate.
- Retry: if transient read failure, retry. If patch would violate invariants, do not retry; revise patch.
- If gate fails: reject patch; require revised patch and re-validation.

---

## Summary: Gate vs Invariant

| Invariant | Post-Ingestion | Pre-RCA | Post-RCA | Pre-Patch |
|-----------|---------------|---------|----------|-----------|
| I1 | ✓ | ✓ | — | ✓ |
| I2 | ✓ | ✓ | — | ✓ |
| I3 | ✓ | — | — | ✓ |
| I4 | — | — | ✓ | ✓ |
| I5 | ✓ | — | — | ✓ |
| I6 | ✓ | ✓ | — | ✓ |
| I7 | ✓ | — | — | ✓ |
| I8 | — | ✓ | ✓ | ✓ |
| I9 | — | ✓ | ✓ | ✓ |
| I10 | — | ✓ | — | ✓ |
| I11 | — | ✓ | — | ✓ |
| I12 | ✓ | ✓ | — | ✓ |
| I13 | ✓ | ✓ | — | ✓ |
| I15 | ✓ | ✓ | — | ✓ |
| I16 | — | — | ✓ | ✓ |
| I17 | ✓ | — | — | ✓ |
| I18 | ✓ | — | — | ✓ |
| I19 | ✓ | — | — | ✓ |
