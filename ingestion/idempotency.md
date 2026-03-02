# Ingestion Idempotency

Canonical IDs, dedupe keys, upsert rules, and late-arriving data handling for deterministic, idempotent ingestion.

---

## Principle

Same input across reruns must produce the same graph state. No duplicate nodes or edges. No conflicting overwrites.

---

## 1. Node Canonical IDs

### Anomaly

| Aspect | Definition |
|--------|------------|
| **Canonical ID** | `anomaly_id` (from source; e.g. `{source}_{timestamp}_{hash}` or UUID) |
| **Dedupe key** | `anomaly_id` |
| **Uniqueness** | One Anomaly per anomaly_id |

### StackFrame

| Aspect | Definition |
|--------|------------|
| **Canonical ID** | `{trace_ref}_{frame_order}` or `hash(trace_ref, frame_order)` |
| **Dedupe key** | `(trace_ref, frame_order)` |
| **Uniqueness** | One StackFrame per (trace_ref, frame_order) |

### File

| Aspect | Definition |
|--------|------------|
| **Canonical ID** | `{repo_ref}_{path}` or `hash(repo_ref, path)`; path normalized (separators, case) |
| **Dedupe key** | `(repo_ref, path)` |
| **Uniqueness** | One File per (repo_ref, path) |

### Commit

| Aspect | Definition |
|--------|------------|
| **Canonical ID** | `{repo_ref}_{sha}` or `sha` (sha is unique per repo) |
| **Dedupe key** | `(repo_ref, sha)` |
| **Uniqueness** | One Commit per (repo_ref, sha) |

### Deployment

| Aspect | Definition |
|--------|------------|
| **Canonical ID** | `deployment_id` (from source) |
| **Dedupe key** | `deployment_id` |
| **Uniqueness** | One Deployment per deployment_id |

---

## 2. Relationship Dedupe Keys

| Relationship | Dedupe Key | Uniqueness |
|--------------|------------|------------|
| HAS_FRAME | `(anomaly_id, stack_frame_id)` | One per (Anomaly, StackFrame) pair |
| IN_FILE | `stack_frame_id` | One per StackFrame when resolution=resolved; none when unknown |
| TOUCHED | `(commit_id, file_id)` | One per (Commit, File) pair (I5) |
| DEPLOYED_COMMIT | `deployment_id` | One per Deployment (I3) |
| RCA_ATTRIBUTED | `(anomaly_id, run_id)` | Multiple per Anomaly (different runs); dedupe by run_id when writing |

---

## 3. Upsert Rules

### Nodes

| Node | If Exists | Action |
|------|-----------|--------|
| **Anomaly** | Match by anomaly_id | Merge mutable fields; do not overwrite immutable. First-write wins for immutable. |
| **StackFrame** | Match by (trace_ref, frame_order) | Skip; StackFrames are immutable once created. |
| **File** | Match by (repo_ref, path) | Merge mutable (canonical_path, previous_paths); do not change path. |
| **Commit** | Match by (repo_ref, sha) | Skip; Commits are immutable. Merge replaces_sha if drift. |
| **Deployment** | Match by deployment_id | Merge mutable (see Late-Arriving); do not change deployment_id. |

### Relationships

| Relationship | If Exists | Action |
|--------------|-----------|--------|
| **HAS_FRAME** | Match by (anomaly_id, stack_frame_id) | Skip; edge is immutable. |
| **IN_FILE** | Match by stack_frame_id | Skip if exists; create only when resolution=resolved. |
| **TOUCHED** | Match by (commit_id, file_id) | Skip; dedupe. |
| **DEPLOYED_COMMIT** | Match by deployment_id | Skip if already linked; else add (late-arriving). |

---

## 4. Immutable vs Mutable

### Immutable (Never Overwrite)

| Node/Edge | Fields |
|-----------|--------|
| **Anomaly** | id (anomaly_id) |
| **StackFrame** | id, trace_ref, frame_order, symbol_name (per trace_ref) |
| **File** | id, path, repo_ref |
| **Commit** | id, sha, timestamp, repo_ref |
| **Deployment** | id (deployment_id) |
| **HAS_FRAME** | (Anomaly, StackFrame), frame_order |
| **IN_FILE** | (StackFrame, File) |
| **TOUCHED** | (Commit, File) |
| **RCA_ATTRIBUTED** | All properties once written (supersede via status, do not overwrite) |

### Mutable (Merge or Update)

| Node | Fields | Rule |
|------|--------|------|
| **Anomaly** | window_id, signal_type, severity, score | Merge if incoming non-null; do not overwrite with null. |
| **File** | canonical_path, previous_paths | Merge on drift; append to previous_paths. |
| **Commit** | replaces_sha | Set when rebase mapping detected. |
| **Deployment** | timestamp, commit_sha, service_ref, version_ref, environment, backfill_status | Update when late-arriving data; see below. |

---

## 5. Late-Arriving Data

### Deployment Commit Lists

| Scenario | Behavior |
|----------|----------|
| **Deployment arrives without commit_sha** | Create Deployment with deployment_id, timestamp, service_ref; set backfill_status=pending. Do not create DEPLOYED_COMMIT. |
| **Commit list arrives later** | Lookup Deployment by deployment_id. Resolve Commits by (repo_ref, sha). Create DEPLOYED_COMMIT. Set backfill_status=complete. |
| **Rerun with same deployment_id + commit_sha** | Idempotent: Deployment exists; DEPLOYED_COMMIT exists; skip. |
| **Rerun with deployment_id only (no commit_sha)** | Idempotent: Deployment exists; skip; backfill_status stays pending. |

### Git Commits After Initial Sync

| Scenario | Behavior |
|----------|----------|
| **New commit arrives** | Create Commit, File, TOUCHED if not exists. Idempotent: (repo_ref, sha) dedupe. |
| **Commit was rebased** | Set Commit.replaces_sha when mapping known. Do not modify sha or timestamp. |

### Anomaly with Delayed Trace

| Scenario | Behavior |
|----------|----------|
| **Anomaly arrives without frames** | Block or quarantine per contracts; do not create Anomaly without HAS_FRAME (I1). |
| **Trace arrives later for existing anomaly_id** | If Anomaly exists with no frames: add StackFrames and HAS_FRAME. If Anomaly has frames: treat as conflict; reject or supersede per policy. |

### File Rename (Drift)

| Scenario | Behavior |
|----------|----------|
| **Rename detected after ingestion** | Update File(old_path).canonical_path, previous_paths. Create File(new_path) if missing. Do not change path on existing File. Idempotent: same rename detection = same updates. |

---

## 6. Conflict Resolution

| Conflict | Rule |
|----------|------|
| **Same anomaly_id, different timestamp** | Reject; anomaly_id is source of truth; first write wins. Or: accept if timestamp is refinement (e.g. more precise); document policy. |
| **Same (trace_ref, frame_order), different symbol_name** | Reject; StackFrame is immutable. |
| **Same (repo_ref, sha), different timestamp** | Reject; Commit is immutable. |
| **Same deployment_id, different commit_sha** | Accept if first had commit_sha=null (backfill). Reject if both non-null and different (data error). |
| **Duplicate TOUCHED** | Skip; dedupe. Log. |
| **Duplicate HAS_FRAME** | Skip; dedupe. |

---

## 7. Rerun Semantics

| Rerun Type | Behavior |
|------------|----------|
| **Full batch rerun, same data** | All nodes and edges match dedupe keys; all upserts are no-ops. Graph unchanged. |
| **Full batch rerun, new data** | New nodes/edges created; existing skipped. Mutable fields merged where applicable. |
| **Partial rerun (e.g. Deployments only)** | Deployments upserted; Commits and Files must exist (from prior Git run). Late-arriving DEPLOYED_COMMIT added. |
| **Out-of-order (Deployments before Git)** | Deployments created with backfill_status=pending. When Git runs, Commits created. Deployments backfill job adds DEPLOYED_COMMIT when Commits exist. |

---

## 8. Summary

| Entity | Canonical ID | Immutable | Mutable |
|--------|--------------|-----------|---------|
| Anomaly | anomaly_id | id | window_id, signal_type, severity, score |
| StackFrame | (trace_ref, frame_order) | all | — |
| File | (repo_ref, path) | id, path, repo_ref | canonical_path, previous_paths |
| Commit | (repo_ref, sha) | id, sha, timestamp, repo_ref | replaces_sha |
| Deployment | deployment_id | id | timestamp, commit_sha, service_ref, backfill_status, etc. |
