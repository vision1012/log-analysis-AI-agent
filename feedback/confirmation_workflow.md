# Confirmation Workflow — Human Feedback on RCA Attributions

Defines the human confirmation workflow: confirm candidate, reject candidate, reject all, rollback accepted. State transitions, audit requirements, and idempotency-safe updates to RCA_ATTRIBUTED edges.

---

## 1. Actions

| Action | Description | Scope |
|--------|-------------|-------|
| **Confirm candidate** | Human validates one candidate as root cause. That attribution becomes accepted. |
| **Reject candidate** | Human says one candidate is not the root cause. That attribution becomes rejected. |
| **Reject all** | Human says none of the candidates are root cause. All candidates for the anomaly become rejected. |
| **Rollback accepted** | Human says the accepted attribution was wrong. Accepted becomes rejected. |

---

## 2. Attribution States

| Status | Description | Terminal |
|--------|-------------|----------|
| **candidate** | Proposed by RCA run; not yet accepted or rejected | No |
| **accepted** | Confirmed as root cause (by human or auto-confirm) | No |
| **rejected** | Rejected; not the root cause | Yes |
| **superseded** | Replaced by a newer attribution (from new RCA run) | Yes |

**Current attribution:** The single attribution with status `accepted`, or (when none accepted) the set of attributions with status `candidate`. An anomaly may have 0–3 candidates and 0 or 1 accepted.

---

## 3. State Transitions

### Confirm Candidate

| From | To | Condition |
|------|-----|-----------|
| candidate | accepted | Human confirms this attribution |
| (other candidates) | rejected | When one candidate is confirmed, all other candidates for the same anomaly (same run or current set) become rejected |

**Rule:** At most one accepted per anomaly. Confirming one candidate implies the others are not root cause.

### Reject Candidate

| From | To | Condition |
|------|-----|-----------|
| candidate | rejected | Human rejects this attribution |

**Rule:** Only the specified attribution changes. Other candidates unchanged.

### Reject All

| From | To | Condition |
|------|-----|-----------|
| candidate (all) | rejected | Human rejects all candidates for the anomaly |

**Rule:** Every attribution with status=candidate for the anomaly becomes rejected. Accepted (if any) unchanged unless rollback is also intended.

### Rollback Accepted

| From | To | Condition |
|------|-----|-----------|
| accepted | rejected | Human says the accepted attribution was wrong |

**Rule:** Only allowed when status is accepted. Candidate cannot be rolled back (use Reject instead).

---

## 4. Transition Table

| Action | Allowed When | Effect |
|--------|--------------|--------|
| Confirm candidate | Target has status=candidate | Target → accepted; other candidates → rejected |
| Reject candidate | Target has status=candidate | Target → rejected |
| Reject all | At least one attribution has status=candidate | All candidates → rejected |
| Rollback accepted | Target has status=accepted | Target → rejected |

| Action | Not Allowed When |
|--------|-------------------|
| Confirm candidate | Target is rejected, superseded, or accepted |
| Reject candidate | Target is rejected or superseded |
| Reject all | No candidates (all rejected/superseded/accepted) |
| Rollback accepted | Target is candidate (use Reject), rejected, or superseded |

---

## 5. Audit Requirements

### Per Feedback Event

| Field | Required | Purpose |
|-------|----------|---------|
| **feedback_id** | Yes | Unique identifier for the feedback event (UUID/ULID) |
| **anomaly_id** | Yes | Anomaly being acted on |
| **action** | Yes | confirm_candidate, reject_candidate, reject_all, rollback_accepted |
| **attribution_id** | Conditional | evidence_ref or (run_id, attributed_frame_id) when action targets one attribution |
| **reviewer_id** | Yes | Who performed the action (user ID, system account) |
| **reviewed_at** | Yes | ISO 8601 UTC |
| **reason** | Optional | Free-text explanation |
| **before_status** | Yes | Status of affected attribution(s) before the action |
| **after_status** | Yes | Status after the action |

### Retention

| Scope | Retention |
|-------|-----------|
| Feedback audit log | 90 days minimum; align with RCA run retention |
| Per-attribution history | Status transitions are permanent on RCA_ATTRIBUTED; audit log captures who/when |

---

## 6. Updating RCA_ATTRIBUTED Without Breaking Idempotency

### Principle

Feedback updates only the `status` property on existing RCA_ATTRIBUTED edges. No new edges created. No edges deleted. Immutable properties (run_id, method, confidence, evidence_ref, attributed_at) are never changed.

### Edge Identity

| Aspect | Rule |
|--------|------|
| **Identity** | Each RCA_ATTRIBUTED edge is uniquely identified by (Anomaly, StackFrame, run_id) or by evidence_ref (bundle_id). |
| **Stability** | Edge identity is immutable. Feedback does not create or delete edges. |
| **Update** | Only `status` is updated. |

### Idempotency Rules

| Scenario | Behavior |
|----------|----------|
| **Same feedback request repeated** | If target attribution already has the target status (e.g. already accepted), no-op. Return success. Idempotent. |
| **Confirm already-accepted** | No-op. Already accepted. Idempotent. |
| **Reject already-rejected** | No-op. Already rejected. Idempotent. |
| **Rollback already-rejected** | Invalid. Reject request (accepted cannot be rolled back if already rejected). |
| **Feedback on terminal status** | Reject request. rejected and superseded are terminal; no transitions allowed. |

### Idempotency Key (Optional)

When the client supplies an idempotency key for a feedback request (e.g. `{anomaly_id}_{action}_{attribution_id}_{reviewer_id}_{timestamp}`):

| Scenario | Behavior |
|----------|----------|
| Same key, no prior feedback | Apply feedback; record key. |
| Same key, prior feedback completed | Return existing result; do not re-apply. Idempotent. |
| Same key, prior feedback in progress | Return in-progress; do not duplicate. |

### Concurrent Feedback

| Scenario | Behavior |
|----------|----------|
| Two humans confirm different candidates for same anomaly | First to complete wins. Second receives conflict (one accepted already exists). Or: lock anomaly during feedback; second request queues or fails. |
| Confirm and Reject all in parallel | First to complete wins. Second may be no-op or conflict depending on state. |
| **Recommended** | Lock anomaly during feedback processing; serialize feedback for same anomaly. |

---

## 7. Workflow Summary

### Confirm Candidate

1. Validate: target attribution exists, has status=candidate.
2. Update: target → accepted.
3. Update: all other candidates for same anomaly → rejected.
4. Audit: log feedback_id, anomaly_id, action=confirm_candidate, attribution_id, reviewer_id, reviewed_at, before/after status.
5. Return: success.

### Reject Candidate

1. Validate: target attribution exists, has status=candidate.
2. Update: target → rejected.
3. Audit: log feedback_id, anomaly_id, action=reject_candidate, attribution_id, reviewer_id, reviewed_at, before/after status.
4. Return: success.

### Reject All

1. Validate: at least one attribution for anomaly has status=candidate.
2. Update: all attributions with status=candidate for anomaly → rejected.
3. Audit: log feedback_id, anomaly_id, action=reject_all, reviewer_id, reviewed_at, count of affected attributions, before/after status.
4. Return: success.

### Rollback Accepted

1. Validate: target attribution exists, has status=accepted.
2. Update: target → rejected.
3. Audit: log feedback_id, anomaly_id, action=rollback_accepted, attribution_id, reviewer_id, reviewed_at, before/after status.
4. Return: success.

---

## 8. Invariant Preservation

| Invariant | Preservation |
|-----------|---------------|
| **I8** (at most one non-superseded per anomaly) | Confirm sets one accepted, others rejected. Reject/Reject all/Rollback only add rejected. Superseded unchanged. |
| **I9** (at most one accepted per anomaly) | Confirm ensures exactly one accepted; others rejected. Rollback removes accepted. |
| **RCA_ATTRIBUTED properties** | run_id, method, confidence, evidence_ref, attributed_at are immutable. Only status changes. |
