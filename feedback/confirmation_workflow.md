# Confirmation Workflow — Human Feedback Lifecycle

Defines the human confirmation lifecycle for RCA attributions: confirm candidate, reject candidate, reject all, rollback. State transitions, invariants, audit requirements, idempotency, and how recurrence and resolution-quality signals are updated.

---

## 1. Human Confirmation Lifecycle

### 1. Confirm Candidate

| Transition | Effect |
|------------|--------|
| **candidate → accepted** | The confirmed attribution becomes the accepted root cause. |
| **All other candidates → rejected** | Every other attribution with status=candidate for the same anomaly becomes rejected. |

**Result:** Anomaly has exactly one accepted root cause.

### 2. Reject Candidate

| Transition | Effect |
|------------|--------|
| **candidate → rejected** | The specified attribution is rejected; not the root cause. |

**Result:** Other candidates unchanged. Anomaly may still have other candidates or an accepted attribution.

### 3. Reject All

| Transition | Effect |
|------------|--------|
| **All candidates → rejected** | Every attribution with status=candidate for the anomaly becomes rejected. |

**Result:** Anomaly has no accepted root cause. All proposed candidates are rejected.

### 4. Rollback

| Transition | Effect |
|------------|--------|
| **accepted → rejected** | The accepted attribution is rolled back; human says it was wrong. |
| **Anomaly returns to no accepted state** | No attribution has status=accepted. Anomaly has no current root cause. |

**Result:** Anomaly may be re-run for RCA (new run_id, new candidates).

---

## 2. State Transition Table

| From | To | Action | Condition |
|------|-----|--------|-----------|
| candidate | accepted | Confirm candidate | Human confirms this attribution |
| candidate | rejected | Reject candidate | Human rejects this attribution |
| candidate | rejected | Reject all | Human rejects all; this candidate among them |
| accepted | rejected | Rollback | Human says accepted was wrong |
| rejected | — | — | Terminal; no transitions |
| superseded | — | — | Terminal; no transitions |

### Action Eligibility

| Action | Allowed When | Not Allowed When |
|--------|--------------|------------------|
| Confirm candidate | Target has status=candidate | Target is rejected, superseded, or accepted |
| Reject candidate | Target has status=candidate | Target is rejected or superseded |
| Reject all | At least one attribution has status=candidate | No candidates (all rejected/superseded/accepted) |
| Rollback | Target has status=accepted | Target is candidate (use Reject), rejected, or superseded |

### Side Effects (Confirm Candidate)

| Action | Additional Updates |
|--------|-------------------|
| Confirm candidate | All other candidates for same anomaly → rejected |

---

## 3. Invariants

### Max One Accepted Per Anomaly

| Invariant | Statement |
|-----------|-----------|
| **I9** | At most one RCA_ATTRIBUTED per anomaly has status=accepted at any time. |

| Action | Preservation |
|--------|--------------|
| **Confirm candidate** | One candidate → accepted; all others → rejected. Exactly one accepted. |
| **Reject candidate** | One → rejected. If another was accepted, it stays. At most one accepted. |
| **Reject all** | All candidates → rejected. Accepted unchanged (if any). At most one accepted. |
| **Rollback** | Accepted → rejected. Zero accepted. Invariant preserved. |

### At Most One Non-Superseded Current Set

| Invariant | Statement |
|-----------|-----------|
| **I8** | At most one RCA_ATTRIBUTED per anomaly has status in {candidate, accepted} that is "current" for human review. (Multi-candidate mode: multiple candidates allowed; at most one accepted.) |

---

## 4. Audit Requirements

### Who, When, Why

| Field | Required | Purpose |
|-------|----------|---------|
| **Who (reviewer_id)** | Yes | User ID or system account that performed the action. Identifies the human (or automated process). |
| **When (reviewed_at)** | Yes | ISO 8601 UTC. When the feedback was applied. |
| **Why (reason)** | Optional | Free-text explanation. Human rationale for confirm, reject, or rollback. |

### Full Audit Record Per Feedback Event

| Field | Required | Purpose |
|-------|----------|---------|
| feedback_id | Yes | Unique identifier (UUID/ULID) |
| anomaly_id | Yes | Anomaly being acted on |
| action | Yes | confirm_candidate, reject_candidate, reject_all, rollback_accepted |
| attribution_id | Conditional | evidence_ref or (run_id, attributed_frame_id) when action targets one attribution |
| reviewer_id | Yes | Who |
| reviewed_at | Yes | When |
| reason | Optional | Why |
| before_status | Yes | Status of affected attribution(s) before |
| after_status | Yes | Status after |
| affected_count | Conditional | For reject_all: number of attributions updated |

### Retention

| Scope | Retention |
|-------|-----------|
| Feedback audit log | 90 days minimum |
| RCA_ATTRIBUTED status | Permanent; status changes are persistent |

---

## 5. Idempotency Behavior

### Principle

Same feedback request applied twice produces the same final state. No duplicate side effects.

### Idempotency Rules

| Scenario | Behavior |
|----------|----------|
| **Confirm same candidate twice** | First: candidate → accepted. Second: already accepted; no-op. Return success. Idempotent. |
| **Reject same candidate twice** | First: candidate → rejected. Second: already rejected; no-op. Return success. Idempotent. |
| **Reject all twice** | First: all candidates → rejected. Second: no candidates; no-op or return success. Idempotent. |
| **Rollback same attribution twice** | First: accepted → rejected. Second: already rejected; invalid (rollback requires accepted). Reject request. |
| **Feedback on terminal status** | rejected, superseded: no transitions allowed. Reject request. |

### Idempotency Key (Optional)

When the client supplies an idempotency key for a feedback request:

| Scenario | Behavior |
|----------|----------|
| Same key, no prior feedback | Apply feedback; record key. |
| Same key, prior feedback completed | Return existing result; do not re-apply. Idempotent. |
| Same key, prior feedback in progress | Return in-progress; do not duplicate. |

### Update Semantics

| Aspect | Rule |
|--------|------|
| **What changes** | Only the `status` property on RCA_ATTRIBUTED edges. |
| **What does not change** | run_id, method, confidence, evidence_ref, attributed_at. Immutable. |
| **No new edges** | Feedback does not create RCA_ATTRIBUTED edges. |
| **No edge deletion** | Feedback does not delete edges. Rejected attributions remain; status=rejected. |

---

## 6. How Recurrence and Resolution-Quality Signals Are Updated

### Recurrence Signal (historical_recurrence)

| Signal | Description | Updated By Feedback? |
|--------|-------------|----------------------|
| **historical_recurrence** | Count of prior RCA_ATTRIBUTED with status in {accepted, candidate} for same File (and service_ref). Normalized. | **Yes, indirectly.** |

**Mechanism:** Feedback changes RCA_ATTRIBUTED status. The graph is updated. Future RCA runs compute historical_recurrence from the current graph state. No explicit recomputation at feedback time.

| Action | Effect on historical_recurrence (Future Runs) |
|--------|-----------------------------------------------|
| **Confirm candidate** | Adds one accepted for that File. historical_recurrence for that File increases in future RCA runs (same or different anomalies). |
| **Reject candidate** | Adds one rejected. Rejected attributions do not count toward historical_recurrence. No increase. |
| **Reject all** | All become rejected. No accepted/candidate for those Files. No increase. |
| **Rollback** | Removes one accepted (now rejected). historical_recurrence for that File decreases in future runs. |

**Rule:** historical_recurrence is derived from prior RCA_ATTRIBUTED with status in {accepted, candidate}. Rejected and superseded do not contribute. When feedback changes status, the next RCA run sees the updated graph and computes accordingly.

### Resolution-Quality Signal (trace_completeness)

| Signal | Description | Updated By Feedback? |
|--------|-------------|----------------------|
| **trace_completeness** | Fraction of frames in trace with resolution=resolved. 1 if all resolved. | **No.** |

**Mechanism:** trace_completeness is derived from StackFrame.resolution (from ingestion). It reflects whether the trace was fully resolved to Files. Human feedback does not change StackFrame.resolution or trace structure. Resolution-quality is fixed at ingestion.

**Rule:** trace_completeness is not updated by the confirmation workflow. It is a property of the anomaly's trace, not of human feedback.

### Summary

| Signal | Source | Feedback Updates |
|--------|--------|------------------|
| historical_recurrence | Prior RCA_ATTRIBUTED (accepted, candidate) | Yes. Status changes alter the set of prior attributions; next RCA run computes different value. |
| trace_completeness | StackFrame.resolution (ingestion) | No. Fixed at ingestion. |
