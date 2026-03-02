# Neo4j Relationships v1 — RCA Platform

Relationships for the 5-node ontology: Anomaly, StackFrame, File, Commit, Deployment.

**MVP criteria:** Only relationships and properties required for determinism, auditability, or time correlation.

---

## 1. HAS_FRAME

| | |
|---|---|
| **Direction** | `(:Anomaly)-[:HAS_FRAME]->(:StackFrame)` |
| **Purpose** | Links an anomaly to the stack frames in its trace. Enables function-level correlation and multi-hop RCA. |

### Properties

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| frame_order | Yes | integer | Position in stack (0 = top/failing frame) |

### Invariants

- Anomaly and StackFrame must share the same `trace_ref`.
- `frame_order` must be unique per Anomaly.
- At least one HAS_FRAME per Anomaly.

---

## 2. RCA_ATTRIBUTED

| | |
|---|---|
| **Direction** | `(:Anomaly)-[:RCA_ATTRIBUTED]->(:StackFrame)` |
| **Purpose** | Records root cause attribution. Links anomaly to the frame identified as root cause. Supports audit, confidence, and run tracking. |

### Properties

| Property | Required | Type | Description |
|----------|----------|------|-------------|
| run_id | Yes | string | RCA run that produced this attribution |
| method | Yes | string | Attribution method (e.g. `deterministic`, `heuristic`, `manual`) |
| confidence | Yes | float | Confidence score (0.0–1.0) |
| status | Yes | string | `candidate`, `accepted`, `rejected`, `superseded` |
| evidence_ref | Yes | string | Reference to evidence (artifact ID, trace_ref, or anomaly_id) |
| attributed_at | Yes | datetime | When attribution was made |

### Status Semantics

| Status | Meaning | Terminal |
|--------|---------|----------|
| candidate | Proposed by RCA run; not yet accepted or rejected | No |
| accepted | Confirmed as root cause (by system or human) | No |
| rejected | Rejected; not the root cause | Yes |
| superseded | Replaced by a newer attribution; no longer current | Yes |

**Superseded:** When a new RCA run writes an attribution for the same anomaly, any existing attribution with status `candidate` or `accepted` must be set to `superseded`. The new attribution becomes `candidate` (or `accepted` if auto-confirmed). Superseded is terminal; no further transitions.

**Current attribution:** The single attribution per anomaly with status `candidate` or `accepted`; use `attributed_at` to resolve if multiple exist (should not occur per invariants).

### Invariants

- Target StackFrame must be connected to the Anomaly via HAS_FRAME.
- Multiple RCA_ATTRIBUTED edges per Anomaly allowed (different runs); use `attributed_at` to resolve current.

---

## 3. IN_FILE

| | |
|---|---|
| **Direction** | `(:StackFrame)-[:IN_FILE]->(:File)` |
| **Purpose** | Links a stack frame to the source file. Join point for stacktrace mapping and commit correlation. |

### Properties

None.

### Invariants

- Each StackFrame with resolution=resolved has exactly one IN_FILE to one File.
- StackFrames with resolution=unknown have no IN_FILE (no sentinel File).
- File must exist before creating the relationship.

---

## 4. TOUCHED

| | |
|---|---|
| **Direction** | `(:Commit)-[:TOUCHED]->(:File)` |
| **Purpose** | Links a commit to files it modified. Enables Git mining and “which commit last changed this file.” |

### Properties

None.

### Invariants

- Commit and File must share the same `repo_ref`.
- One TOUCHED per (Commit, File) pair.

---

## 5. DEPLOYED_COMMIT

| | |
|---|---|
| **Direction** | `(:Deployment)-[:DEPLOYED_COMMIT]->(:Commit)` |
| **Purpose** | Links a deployment to the commit it deployed. Enables deployment timing validation and commit correlation. |

### Properties

None.

### Invariants

- Deployment `commit_sha` must match Commit `sha`.
- Deployment and Commit must be for the same logical service (via `service_ref` / repo scope).

---

## Summary

| Relationship | From | To | Purpose |
|--------------|------|-----|---------|
| HAS_FRAME | Anomaly | StackFrame | Trace membership |
| RCA_ATTRIBUTED | Anomaly | StackFrame | Root cause attribution |
| IN_FILE | StackFrame | File | Frame → file mapping |
| TOUCHED | Commit | File | Commit → file mapping |
| DEPLOYED_COMMIT | Deployment | Commit | Deployment → commit mapping |

---

## Removals (MVP Trim)

| Removed | Why |
|---------|-----|
| **RCA_ATTRIBUTED.reviewer_feedback** | Not required for MVP auditability; human review can be added later. |
| **IN_FILE.line_number** | Display-only; not used for determinism, auditability, or time correlation. Line numbers are excluded from trace_ref. |
| **TOUCHED.change_type** | Not needed for “which commit last modified”; determinism only needs the link. |
| **DEPLOYED_COMMIT.version_ref** | Not needed for time correlation; Deployment.timestamp and DEPLOYED_COMMIT→Commit are sufficient. |

**Promoted:** `attributed_at` from optional to required on RCA_ATTRIBUTED — needed for audit (when) and to resolve current vs superseded attribution.
