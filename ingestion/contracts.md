# Ingestion Contracts — RCA Platform

Contracts for each ingestion source. MVP, deterministic. No raw logs or proprietary code in graph.

---

## Overview

| Source | Produces | Order |
|--------|----------|-------|
| Logs/Stacktraces | Anomaly, StackFrame, HAS_FRAME, IN_FILE | First (anomalies + traces) |
| Git (PyDriller) | Commit, File, TOUCHED | Second (before or with logs; Files must exist for IN_FILE) |
| Deployments | Deployment, DEPLOYED_COMMIT | Third (after Git; Commits must exist) |
| JIRA | — | Optional later |

**Dependency:** Git must run before or with Logs so File nodes exist for StackFrame→IN_FILE→File.

---

## 1. Logs / Stacktraces

### Purpose

Ingest anomaly signals and stack traces. Produces Anomaly and StackFrame nodes; links via HAS_FRAME and IN_FILE.

### Required Fields (Must)

| Field | Type | Constraint | Graph Mapping |
|-------|------|------------|---------------|
| anomaly_id | string | Unique; max 64 chars | Anomaly.id |
| timestamp | string | ISO 8601 UTC | Anomaly.timestamp |
| trace_ref | string | 32 hex chars; stable fingerprint per graph/trace_ref rules | Anomaly.trace_ref, StackFrame.trace_ref |
| service_ref | string | Max 64 chars | Anomaly.service_ref |
| frames | array | At least one frame | — |
| frames[].symbol_name | string | Max 256 chars | StackFrame.symbol_name |
| frames[].file_path | string | Repo-relative; max 512 chars | Resolve to File; StackFrame -[:IN_FILE]-> File |
| frames[].frame_order | integer | 0 to n−1; unique per trace | HAS_FRAME.frame_order |
| repo_ref | string | Max 64 chars; same for all frames in trace | File.repo_ref when resolving |

### Optional Fields (Nice-to-Have)

| Field | Type | Graph Mapping |
|-------|------|---------------|
| window_id | string | Anomaly.window_id |
| signal_type | string | Anomaly.signal_type |
| severity | string | Anomaly.severity |
| score | float | Anomaly.score |
| frames[].line_number | integer | Display only; not in trace_ref |
| parser_version | string | Parser version that produced trace_ref; for mismatch resolution |
| schema_version | string | Parsing output contract version; for compatibility checks |

### Graph Mapping

| Input | Node/Edge | Notes |
|-------|-----------|-------|
| anomaly_id, timestamp, trace_ref, service_ref, parser_version, schema_version | Anomaly | Create or merge by id |
| frames[] | StackFrame | One per frame; id = hash(trace_ref, frame_order) or similar |
| Anomaly + StackFrame | HAS_FRAME | frame_order on edge |
| frames[].file_path + repo_ref | File | Lookup or create; then StackFrame -[:IN_FILE]-> File |

### Quality Gates

| Gate | Invariants | Depends On |
|------|------------|------------|
| Post-ingestion | I1 (Anomaly has HAS_FRAME), I2 (resolved frames have IN_FILE; entire trace unresolved = block), I6, I7, I12, I17 | trace_ref, frames, file_path, repo_ref |
| Pre-RCA | I1, I2, I6, I12, I10 (service_ref) | Same |

### Failure Behavior

| Condition | Behavior | Severity |
|-----------|----------|----------|
| Missing anomaly_id, timestamp, trace_ref, service_ref | Block ingestion | Blocker |
| Empty frames or missing symbol_name, file_path, frame_order | Block ingestion | Blocker |
| File not found for file_path + repo_ref | Mark resolution=unknown; create StackFrame without IN_FILE. Block only if all frames unresolved. | Degrade (partial) / Block (entire) |
| trace_ref mismatch (computed vs provided, same parser_version) | Block | Blocker |
| trace_ref mismatch (parser_version differs, schema incompatible, or version missing) | Quarantine | Quarantine |
| frame_order gaps or duplicates | Block ingestion | Blocker |
| Missing window_id, score | Log; proceed | Warn |

---

## 2. Git (PyDriller)

### Purpose

Ingest commit history and file modifications. Produces Commit and File nodes; links via TOUCHED. Files are required for StackFrame→IN_FILE.

### Required Fields (Must)

| Field | Type | Constraint | Graph Mapping |
|-------|------|------------|---------------|
| sha | string | 40 chars (git SHA-1) | Commit.sha, Commit.id |
| timestamp | string | ISO 8601 UTC | Commit.timestamp |
| repo_ref | string | Max 64 chars | Commit.repo_ref, File.repo_ref |
| modified_files | array | At least one path | — |
| modified_files[].path | string | Repo-relative; max 512 chars | File.path; Commit -[:TOUCHED]-> File |

### Optional Fields (Nice-to-Have)

| Field | Type | Graph Mapping |
|-------|------|---------------|
| author | string | Commit (if added to model) |
| message | string | Commit (if added to model) |
| modified_files[].change_type | string | added, modified, deleted (not used in v1) |

### Graph Mapping

| Input | Node/Edge | Notes |
|-------|-----------|-------|
| sha, timestamp, repo_ref | Commit | Create or merge by (sha, repo_ref) |
| modified_files[].path + repo_ref | File | Lookup or create |
| Commit + File | TOUCHED | One per (Commit, File) pair |

### Quality Gates

| Gate | Invariants | Depends On |
|------|------------|------------|
| Post-ingestion | I5 (no duplicate TOUCHED), I15 (Commit timestamp), I18 (File has IN_FILE or TOUCHED), I19 (Commit has TOUCHED) | sha, timestamp, repo_ref, modified_files |
| Pre-RCA | I15 | Same |

### Failure Behavior

| Condition | Behavior | Severity |
|-----------|----------|----------|
| Missing sha, timestamp, repo_ref | Block ingestion | Blocker |
| Empty modified_files | Block or degrade (I19); Commit without TOUCHED | Degrade |
| Duplicate TOUCHED for (Commit, File) | Deduplicate; log | Degrade |
| Invalid sha format | Block ingestion | Blocker |
| Path normalization failure | Block that file; continue with others | Degrade |

---

## 3. Deployments

### Purpose

Ingest deployment events. Produces Deployment nodes; links to Commit via DEPLOYED_COMMIT. Requires Commits to exist (Git ingestion first).

### Required Fields (Must)

| Field | Type | Constraint | Graph Mapping |
|-------|------|------------|---------------|
| deployment_id | string | Unique; max 64 chars | Deployment.id |
| timestamp | string | ISO 8601 UTC | Deployment.timestamp |
| commit_sha | string | 40 chars; must exist in graph | Resolve to Commit; Deployment -[:DEPLOYED_COMMIT]-> Commit |
| service_ref | string | Max 64 chars | Deployment.service_ref |

### Optional Fields (Nice-to-Have)

| Field | Type | Graph Mapping |
|-------|------|---------------|
| version_ref | string | Deployment.version_ref |
| environment | string | Deployment.environment |
| repo_ref | string | For Commit lookup scope |

### Graph Mapping

| Input | Node/Edge | Notes |
|-------|-----------|-------|
| deployment_id, timestamp, commit_sha, service_ref | Deployment | Create by id |
| commit_sha | Commit | Lookup; must exist |
| Deployment + Commit | DEPLOYED_COMMIT | Deployment -[:DEPLOYED_COMMIT]-> Commit |

### Quality Gates

| Gate | Invariants | Depends On |
|------|------------|------------|
| Post-ingestion | I3 (Deployment has DEPLOYED_COMMIT), I13 (Deployment timestamp) | deployment_id, timestamp, commit_sha, service_ref |
| Pre-RCA | I3, I10 (service_ref consistency), I11 (Deployment–Commit scope), I13 | Same |

### Failure Behavior

| Condition | Behavior | Severity |
|-----------|----------|----------|
| Missing deployment_id, timestamp, commit_sha, service_ref | Block ingestion | Blocker |
| Commit not found for commit_sha | Block Deployment creation; or create with backfill_status=pending | Blocker (or Degrade if pending allowed) |
| service_ref inconsistent with Commit scope | Block DEPLOYED_COMMIT; log | Blocker |
| Missing version_ref, environment | Log; proceed | Warn |

---

## 4. JIRA (Optional Later)

### Purpose

Link incidents to tickets; enrich RCA with ticket metadata. Not in MVP.

### Planned Fields (Future)

| Field | Type | Graph Mapping |
|-------|------|---------------|
| ticket_id | string | New node or Anomaly property |
| anomaly_id | string | Link to Anomaly |
| status, assignee, etc. | — | TBD |

### Notes

- No graph nodes/edges defined for v1.
- Add when ticket correlation is required for RCA or audit.

---

## Summary: Failure Behavior by Severity

| Severity | Action |
|----------|--------|
| **Block** | Reject record; do not write to graph; fail batch if critical |
| **Degrade** | Log; apply remediation if possible; mark batch degraded; RCA may run with lower confidence |
| **Warn** | Log; proceed; no batch impact |

---

## Ingestion Order

1. **Git** — Commits and Files must exist before StackFrames can link via IN_FILE.
2. **Logs/Stacktraces** — Anomalies and StackFrames; requires Files from Git.
3. **Deployments** — Requires Commits from Git.

**Parallel:** Git and Logs can run in parallel if Files are created on-demand from Git before or during Log ingestion (e.g. lazy File creation when frame references unknown path).
