# Confirmation Workflow — Human Feedback Lifecycle

Defines the human confirmation lifecycle for RCA attributions: confirm candidate, reject candidate, reject all, rollback. State transitions, invariants, audit requirements, idempotency, and how accepted/rejected edges impact Historical Recurrence and Resolution Quality signals.

---

## 1. Human Confirmation Lifecycle

### Confirm Candidate

| Transition | Effect |
|------------|--------|
| **candidate → accepted** | The confirmed attribution becomes the accepted root cause. |
| **All other candidates → rejected** | Every other attribution with status=candidate for the same anomaly becomes rejected. |

**Result:** Anomaly has exactly one accepted root cause.

### Reject Candidate

| Transition | Effect |
|------------|--------|
| **candidate → rejected** | The specified attribution is rejected; not the root cause. |

**Result:** Other candidates unchanged. Anomaly may still have other candidates or an accepted attribution.

### Reject All

| Transition | Effect |
|------------|--------|
| **All candidates → rejected** | Every attribution with status=candidate for the anomaly becomes rejected. |
| **Anomaly has no accepted root cause** | No attribution has status=accepted. |

**Result:** All proposed candidates rejected. Anomaly has no current root cause.

### Rollback

| Transition | Effect |
|------------|--------|
| **accepted → rejected** | The accepted attribution is rolled back; human says it was wrong. |
| **Anomaly returns to no accepted root cause** | No attribution has status=accepted. |

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

### Required Fields

| Field | Required | Purpose |
|-------|----------|---------|
| **actor_id** | Yes | User ID or system account that performed the action. Identifies who performed the feedback. |
| **timestamp** | Yes | ISO 8601 UTC. When the feedback was applied. |
| **reason** | Optional | Free-text explanation. Human rationale for confirm, reject, or rollback. |

### Full Audit Record Per Feedback Event

| Field | Required | Purpose |
|-------|----------|---------|
| feedback_id | Yes | Unique identifier (UUID/ULID) |
| anomaly_id | Yes | Anomaly being acted on |
| action | Yes | confirm_candidate, reject_candidate, reject_all, rollback_accepted |
| attribution_id | Conditional | evidence_ref or (run_id, attributed_frame_id) when action targets one attribution |
| actor_id | Yes | Who performed the action |
| timestamp | Yes | When the action was applied |
| reason | Optional | Why (human rationale) |
| before_status | Yes | Status of affected attribution(s) before |
| after_status | Yes | Status after |
| affected_count | Conditional | For reject_all: number of attributions updated |

### Retention

| Scope | Retention |
|-------|-----------|
| Feedback audit log | 90 days minimum |
| RCA_ATTRIBUTED status | Permanent; status changes are persistent |

---

## 5. Idempotency Behavior for Repeated Actions

### Principle

Same feedback action applied twice produces the same final state. No duplicate side effects.

### Repeated Action Behavior

| Action | First application | Second application (repeated) |
|--------|-------------------|------------------------------|
| **Confirm candidate** | candidate → accepted; others → rejected | Target already accepted; no-op. Return success. Idempotent. |
| **Reject candidate** | candidate → rejected | Target already rejected; no-op. Return success. Idempotent. |
| **Reject all** | All candidates → rejected | No candidates; no-op. Return success. Idempotent. |
| **Rollback** | accepted → rejected | Target already rejected; invalid. Reject request (rollback requires accepted). |

### Terminal Status

| Status | Repeated action |
|--------|-----------------|
| **rejected** | No transitions allowed. Reject request. |
| **superseded** | No transitions allowed. Reject request. |

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

## 6. Impact on Historical Recurrence and Resolution Quality Signals

### Historical Recurrence Signal

| Signal | Description | Counted in |
|--------|-------------|------------|
| **historical_recurrence** | Prior attributions for same File (and service_ref). Normalized count. | RCA_ATTRIBUTED with status in {accepted, candidate} only. |

**Rule:** Rejected and superseded attributions do **not** contribute to historical_recurrence.

### How Accepted Edges Impact Historical Recurrence

| Action | Effect |
|--------|--------|
| **Confirm candidate** | One attribution → accepted. That File gains one prior accepted. historical_recurrence for that File **increases** in future RCA runs (same or different anomalies). |
| **Reject candidate** | One attribution → rejected. Rejected does not count. historical_recurrence **unchanged** (no prior accepted/candidate added). |
| **Reject all** | All candidates → rejected. No accepted. historical_recurrence **unchanged** for those Files. |
| **Rollback** | One accepted → rejected. That File loses one prior accepted. historical_recurrence for that File **decreases** in future RCA runs. |

### Summary: Accepted vs Rejected

| Status | Contributes to historical_recurrence? |
|--------|--------------------------------------|
| accepted | Yes |
| candidate | Yes |
| rejected | No |
| superseded | No |

**Mechanism:** Feedback changes status. Graph is updated. Future RCA runs compute historical_recurrence from current graph state. No explicit recomputation at feedback time.

### Resolution Quality Signal (trace_completeness)

| Signal | Description | Source |
|--------|-------------|--------|
| **trace_completeness** | Fraction of frames in trace with resolution=resolved. 1 if all resolved. | StackFrame.resolution (from ingestion). |

### How Accepted/Rejected Edges Impact Resolution Quality

| Impact | Rule |
|--------|------|
| **None** | trace_completeness is derived from StackFrame.resolution. Human feedback does not change StackFrame.resolution or trace structure. Resolution quality is fixed at ingestion. |
| **Accepted/rejected** | Do not affect trace_completeness. |

**Rule:** trace_completeness is not updated by the confirmation workflow. It is a property of the anomaly's trace, not of human feedback.

### Summary

| Signal | Updated by feedback? | How |
|--------|----------------------|-----|
| **historical_recurrence** | Yes, indirectly | Status changes alter the set of prior accepted/candidate attributions. Next RCA run computes different value. |
| **trace_completeness** | No | Fixed at ingestion. StackFrame.resolution unchanged by feedback. |
