# RCA Run Lifecycle and run_id Semantics

Production specification for RCA run lifecycle, idempotency, concurrency, status transitions, human feedback, and rollback.

---

## Entities

| Entity | Description |
|--------|-------------|
| **RCA Run** | A single execution of the RCA pipeline for one or more anomalies. Has run_id. |
| **Attribution** | An RCA_ATTRIBUTED edge linking Anomaly to StackFrame. Has status. |
| **Incident** | An Anomaly (or set of anomalies) being analyzed. |

---

## run_id Semantics

| Rule | Description |
|------|-------------|
| **Uniqueness** | run_id is globally unique per RCA run. Format: UUID, ULID, or `{source}_{timestamp}_{nonce}`. |
| **Stability** | run_id is immutable once assigned. Never reused. |
| **Scope** | One run_id per RCA run. A run may produce multiple attributions (one per anomaly in scope). |
| **Reference** | run_id is stored on RCA_ATTRIBUTED and in the evidence bundle. Used for audit and idempotency. |

---

## Idempotency Rules (Same Incident Rerun)

### Idempotency Key

When a client requests an RCA run, it may supply an **idempotency key** (e.g. `{anomaly_id}_{window_id}` or client-generated UUID). The key is scoped to the run request, not the run itself.

### Rules

| Scenario | Behavior |
|----------|----------|
| **Same idempotency key, no prior run** | Create new run; assign run_id; execute RCA; return result. |
| **Same idempotency key, prior run completed** | Return existing result; do not re-execute. run_id unchanged. |
| **Same idempotency key, prior run in progress** | Return in-progress status; do not start duplicate run. |
| **Same idempotency key, prior run failed** | Configurable: (a) return failed result, or (b) allow retry with same key (new run_id, same key). |
| **No idempotency key** | Every request is a new run; new run_id each time. |

### Deterministic run_id (Alternative)

If run_id is derived from inputs (e.g. `hash(anomaly_id, window_id, rca_version)`), then reruns with same inputs produce same run_id. Idempotency is implicit: second run finds existing run_id and returns cached result.

---

## Concurrency Rules (Two Runs in Parallel)

### Same Anomaly, Two Runs

| Scenario | Behavior |
|----------|----------|
| **Run A and Run B both start for same anomaly** | One of: (a) Run B is rejected (anomaly locked), or (b) Both run; last to complete wins. |
| **Recommended** | Lock anomaly at run start; second run receives "anomaly in use" and fails or queues. |
| **Alternative** | Both run; first to write attribution wins; second run's attribution is rejected (duplicate current). |

### Different Anomalies

| Scenario | Behavior |
|----------|----------|
| **Run A for anomaly 1, Run B for anomaly 2** | No conflict. Both run in parallel. |

### Lock Scope

- Lock granularity: per anomaly_id (or per batch of anomaly_ids).
- Lock duration: from run start until attributions are written (or run fails).
- Lock release: on run completion, failure, or timeout.

---

## Attribution Status: State Machine

### States

| State | Description | Terminal |
|-------|-------------|----------|
| **candidate** | Attribution proposed by RCA run; not yet accepted or rejected. | No |
| **accepted** | Attribution confirmed as root cause (by system or human). | No |
| **rejected** | Attribution rejected; not the root cause. | Yes |
| **superseded** | Attribution replaced by a newer one; no longer current. | Yes |

**Superseded semantics:** When a new RCA run writes an attribution for the same anomaly, any existing attribution with status `candidate` or `accepted` must be set to `superseded`. The new attribution is written with status `candidate` (or `accepted` if auto-confirmed). Superseded is terminal; no further transitions. See relationships.md for full status semantics.

### Transitions (Plain English)

1. **candidate → accepted**  
   - Trigger: Human confirms, or auto-confirm rule passes (e.g. confidence above threshold).  
   - Effect: Attribution becomes the current root cause for the anomaly.

2. **candidate → rejected**  
   - Trigger: Human rejects, or validation fails, or duplicate candidate for same anomaly.  
   - Effect: Attribution is not the root cause; excluded from RCA results.

3. **accepted → superseded**  
   - Trigger: New RCA run produces a new attribution for the same anomaly.  
   - Effect: Old attribution is superseded; new attribution becomes candidate (or accepted if auto-confirmed).

4. **accepted → rejected**  
   - Trigger: Human rollback ("this was wrong").  
   - Effect: Attribution is no longer the root cause; anomaly has no current accepted attribution.

5. **superseded → (no transition)**  
   - Superseded is terminal for that attribution. No further transitions.

6. **rejected → (no transition)**  
   - Rejected is terminal. No further transitions.

### Transition Table

| From | To | Trigger | Who |
|------|-----|---------|-----|
| candidate | accepted | Confirm | Human or auto-confirm rule |
| candidate | rejected | Reject | Human or validation |
| accepted | superseded | New attribution written | System (new RCA run) |
| accepted | rejected | Rollback | Human |
| superseded | — | — | Terminal |
| rejected | — | — | Terminal |

### Invariant

At most one attribution per anomaly has status **accepted** at any time. At most one has status **candidate** at any time (or none, if all are accepted/rejected/superseded).

---

## Human Feedback Integration

### Actions Available to Human

| Action | Effect |
|--------|--------|
| **Confirm** | candidate → accepted. Human validates the attribution. |
| **Reject** | candidate → rejected. Human says "not the root cause." |
| **Rollback** | accepted → rejected. Human says "this was wrong; undo." |

### Feedback Storage

| Field | Location | Purpose |
|-------|----------|---------|
| reviewer_id | Optional on RCA_ATTRIBUTED or audit log | Who performed the action |
| reviewed_at | Optional on RCA_ATTRIBUTED or audit log | When |
| reviewer_feedback | Optional (per earlier trim) or audit log | Free-text notes |

For MVP, feedback can be stored in audit log only; RCA_ATTRIBUTED keeps status only.

### Feedback Timing

- **Confirm/Reject:** Only when status is candidate.
- **Rollback:** Only when status is accepted.

---

## Rollback Rules (Accepted → Rejected)

### When Rollback Is Allowed

| Condition | Allowed? |
|-----------|----------|
| Attribution status is accepted | Yes |
| Attribution status is candidate | No (use Reject instead) |
| Attribution status is superseded | No (already superseded) |
| Attribution status is rejected | No (already rejected) |

### Effect of Rollback

| Before | After |
|--------|-------|
| One accepted attribution for anomaly | No accepted attribution |
| Anomaly has current root cause | Anomaly has no current root cause |

### After Rollback

- Anomaly may be re-run for RCA (new run_id, new candidate).
- Superseded attributions remain superseded; they are not revived.
- Rejected attribution remains rejected.

### Audit

- Rollback must be logged: anomaly_id, attribution run_id, reviewer, timestamp, reason (optional).

---

## RCA Run State Machine (Run-Level)

### States

| State | Description |
|-------|-------------|
| **queued** | Run requested; not yet started |
| **running** | RCA in progress |
| **completed** | RCA finished; attributions written |
| **failed** | RCA failed (error, timeout, validation) |
| **cancelled** | Run cancelled before completion |

### Transitions

| From | To | Trigger |
|------|-----|---------|
| queued | running | Worker picks up run |
| running | completed | RCA finishes; attributions written |
| running | failed | Error, timeout, or validation failure |
| queued | cancelled | Human or system cancels |
| running | cancelled | Human or system cancels |

### Terminal States

- **completed**, **failed**, **cancelled** are terminal. No further transitions.

---

## Summary: Decision Table

| Question | Answer |
|----------|--------|
| Same incident rerun with same idempotency key? | Return existing result; no re-run |
| Two runs for same anomaly in parallel? | Lock anomaly; second run fails or queues |
| How does candidate become accepted? | Human confirms or auto-confirm rule |
| How does accepted become rejected? | Human rollback |
| How does accepted become superseded? | New RCA run writes new attribution |
| Can superseded be revived? | No |
| Can rejected be revived? | No |
