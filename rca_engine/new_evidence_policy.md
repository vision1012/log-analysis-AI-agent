# New Evidence Policy — Automatic Rerun Triggers

Defines what counts as "new evidence" that should trigger an automatic RCA rerun. For each: trigger behavior, cooldown, and audit logging. No code.

---

## 1. New Evidence Types

| Evidence type | Description |
|---------------|-------------|
| **Deployment backfill completed** | Deployment had backfill_status=pending; now has DEPLOYED_COMMIT. |
| **Commit history backfilled** | Git sync added new commits (TOUCHED) or files that affect an anomaly's trace. |
| **StackFrame resolution changed** | StackFrame resolution changed from unknown→resolved (IN_FILE created). |
| **Parser version changed** | Stacktrace parser upgraded; trace_ref or frame structure may differ. |
| **Anomaly window merged/split** | Anomaly's window_id or time window was merged or split (e.g. batch correction). |

---

## 2. Deployment Backfill Completed

### Trigger Behavior

| Event | When Deployment.backfill_status transitions from pending → complete. |
|-------|---------------------------------------------------------------------|
| **Scope** | Anomalies whose service_ref matches the Deployment and whose timestamp is within the deployment's relevance window (e.g. Deployment.timestamp within N days of Anomaly.timestamp). |
| **Action** | Enqueue RCA run for each affected anomaly. New run_id. |

### Cooldown

| Rule | Description |
|------|-------------|
| **Per anomaly** | Do not re-trigger for same anomaly within cooldown period (e.g. 1 hour) after last RCA run for that anomaly. |
| **Per deployment** | If multiple deployments backfill in quick succession, batch anomalies; one run per anomaly per cooldown window. |
| **Default cooldown** | 1 hour. Configurable. |

### Audit Logging

| Field | Logged |
|-------|--------|
| event_type | deployment_backfill_complete |
| deployment_id | Deployment that completed backfill |
| service_ref | Affected service |
| anomaly_ids | Anomalies enqueued for rerun |
| run_ids | New run_ids assigned |
| timestamp | When trigger fired |

---

## 3. Commit History Backfilled

### Trigger Behavior

| Event | When Git sync adds new commits (TOUCHED) or files that affect files in an anomaly's trace. |
|-------|--------------------------------------------------------------------------------------------|
| **Scope** | Anomalies whose trace has Files that gained new TOUCHED edges (new last-touch) or whose trace now resolves to new Files. |
| **Action** | Enqueue RCA run for each affected anomaly. New run_id. |

### Detection

| Method | Description |
|--------|-------------|
| **File-level** | Files in anomaly traces (via IN_FILE from StackFrames) now have new TOUCHED from commits not in graph at last RCA. |
| **Batch** | Git sync completes; compare affected files to anomaly traces. Enqueue anomalies with overlapping files. |

### Cooldown

| Rule | Description |
|------|-------------|
| **Per anomaly** | Do not re-trigger for same anomaly within cooldown period (e.g. 1 hour) after last RCA run. |
| **Git sync batch** | If Git sync runs frequently, aggregate; trigger once per cooldown per anomaly. |
| **Default cooldown** | 1 hour. Configurable. |

### Audit Logging

| Field | Logged |
|-------|--------|
| event_type | commit_history_backfilled |
| repo_ref | Repo affected |
| commit_ids | New commits (or count) |
| file_ids | Files with new TOUCHED |
| anomaly_ids | Anomalies enqueued |
| run_ids | New run_ids |
| timestamp | When trigger fired |

---

## 4. StackFrame Resolution Changed (unknown → resolved)

### Trigger Behavior

| Event | When a StackFrame's resolution changes from unknown to resolved (IN_FILE created). |
|-------|-----------------------------------------------------------------------------------|
| **Scope** | Anomalies that have HAS_FRAME to the affected StackFrame. |
| **Action** | Enqueue RCA run for each affected anomaly. New run_id. |

### Detection

| Method | Description |
|--------|-------------|
| **Frame-level** | StackFrame created or updated: resolution was unknown, now resolved. IN_FILE created. |
| **Trace-level** | Anomaly's trace (HAS_FRAME) now has more resolved frames. trace_completeness increases. |

### Cooldown

| Rule | Description |
|------|-------------|
| **Per anomaly** | Do not re-trigger for same anomaly within cooldown period (e.g. 1 hour). |
| **Bulk re-parse** | If many frames resolve at once (e.g. repo sync), batch anomalies; one run per anomaly per cooldown. |
| **Default cooldown** | 1 hour. Configurable. |

### Audit Logging

| Field | Logged |
|-------|--------|
| event_type | stackframe_resolution_changed |
| stack_frame_id | StackFrame that gained resolution |
| anomaly_ids | Anomalies with HAS_FRAME to this frame |
| trace_ref | Trace affected |
| run_ids | New run_ids |
| timestamp | When trigger fired |

---

## 5. Parser Version Changed

### Trigger Behavior

| Event | When parser_version or schema_version changes on the stacktrace parser. |
|-------|-----------------------------------------------------------------------|
| **Scope** | Anomalies whose trace was parsed with the old parser version. Optionally: all anomalies in a time window, or only those re-parsed. |
| **Action** | Enqueue RCA run for each affected anomaly. New run_id. |

### Detection

| Method | Description |
|--------|-------------|
| **Re-parse** | Anomalies whose traces are re-parsed with new parser. New trace_ref or resolution may result. |
| **Version flag** | Anomaly.parser_version or Anomaly.schema_version updated. |
| **Batch** | Parser upgrade triggers batch re-parse; re-parse completion triggers RCA for affected anomalies. |

### Cooldown

| Rule | Description |
|------|-------------|
| **Per anomaly** | Do not re-trigger for same anomaly within cooldown period (e.g. 1 hour). |
| **Parser upgrade** | Often one-time batch. Cooldown applies per anomaly across the batch. |
| **Default cooldown** | 1 hour. Configurable. |

### Audit Logging

| Field | Logged |
|-------|--------|
| event_type | parser_version_changed |
| old_parser_version | Previous version |
| new_parser_version | New version |
| anomaly_ids | Anomalies enqueued |
| run_ids | New run_ids |
| timestamp | When trigger fired |

---

## 6. Anomaly Window Merged/Split

### Trigger Behavior

| Event | When an anomaly's window_id or time window is merged or split (e.g. batch correction, window consolidation). |
|-------|-------------------------------------------------------------------------------------------------------------|
| **Scope** | Anomalies whose window_id changed or whose time window was affected by merge/split. |
| **Action** | Enqueue RCA run for each affected anomaly. New run_id. |

### Detection

| Method | Description |
|--------|-------------|
| **Window update** | Anomaly.window_id or Anomaly.timestamp updated. |
| **Merge** | Multiple anomalies merged into one; or one split into multiple. |
| **Batch job** | Window merge/split job completes; emits list of affected anomaly_ids. |

### Cooldown

| Rule | Description |
|------|-------------|
| **Per anomaly** | Do not re-trigger for same anomaly within cooldown period (e.g. 1 hour). |
| **Bulk merge/split** | Batch job may affect many anomalies; one run per anomaly per cooldown. |
| **Default cooldown** | 1 hour. Configurable. |

### Audit Logging

| Field | Logged |
|-------|--------|
| event_type | anomaly_window_merged_or_split |
| anomaly_ids | Anomalies affected |
| old_window_id | Previous window (if applicable) |
| new_window_id | New window (if applicable) |
| run_ids | New run_ids |
| timestamp | When trigger fired |

---

## 7. Cooldown Summary

| Evidence type | Default cooldown | Purpose |
|---------------|------------------|---------|
| Deployment backfill | 1 hour | Avoid rapid re-runs when multiple deployments backfill |
| Commit history | 1 hour | Avoid re-run per commit during sync |
| StackFrame resolution | 1 hour | Avoid re-run per frame during bulk re-parse |
| Parser version | 1 hour | Batch re-parse; one run per anomaly |
| Anomaly window | 1 hour | Batch merge/split; one run per anomaly |

**Rule:** Same anomaly cannot be re-triggered within cooldown of its last RCA run (completed or failed). Idempotency key for auto reruns: e.g. `{anomaly_id}_{evidence_type}_{cooldown_window}` to dedupe within window.

---

## 8. Audit Logging Summary

| Requirement | Content |
|-------------|---------|
| **Per trigger** | event_type, timestamp, anomaly_ids, run_ids, evidence-specific fields |
| **Retention** | 90 days minimum |
| **Purpose** | Audit: why was this anomaly re-run? Trace: evidence type → run_id. |

---

## 9. Trigger Priority (When Multiple Evidence Types)

| Scenario | Behavior |
|----------|----------|
| **Multiple evidence types in same cooldown** | One run per anomaly. First trigger wins; others dedupe (anomaly already enqueued or in cooldown). |
| **Same anomaly, different evidence** | Cooldown is per anomaly, not per evidence type. One run per cooldown window. |
| **Order** | No priority ordering. First to fire within cooldown enqueues; subsequent triggers within cooldown are skipped. |
