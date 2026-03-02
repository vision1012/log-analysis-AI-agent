# Hard Invariants — Neo4j v1

Invariants that guarantee deterministic RCA. Nodes: Anomaly, StackFrame, File, Commit, Deployment. Relationships: HAS_FRAME, IN_FILE, TOUCHED, DEPLOYED_COMMIT, RCA_ATTRIBUTED.

---

## Missing Edges

### I1. Every Anomaly has at least one HAS_FRAME

| | |
|---|---|
| **Statement** | For every Anomaly node, there exists at least one outgoing HAS_FRAME to a StackFrame. |
| **Why it matters** | Without frames, function-level RCA is impossible. Anomaly cannot be traversed to code. |
| **Severity** | Blocker |
| **Remediation** | Reject ingestion of Anomaly until trace is available; or quarantine and exclude from RCA. |

---

### I2. StackFrame has IN_FILE when resolution=resolved

| | |
|---|---|
| **Statement** | For every StackFrame with resolution=resolved, there exists exactly one outgoing IN_FILE to a File. StackFrames with resolution=unknown have no IN_FILE. |
| **Why it matters** | Frame→File is the join point for commit correlation. Resolved frames must link to File. Unresolved frames do not; no sentinel File. |
| **Severity** | Blocker when entire trace unresolved; Degrade when partial. |
| **Remediation** | Partial trace: proceed with resolved frames; degrade confidence. Entire trace unresolved: reject or quarantine anomaly. |

---

### I3. Every Deployment has exactly one DEPLOYED_COMMIT

| | |
|---|---|
| **Statement** | For every Deployment node, there exists exactly one outgoing DEPLOYED_COMMIT to a Commit. |
| **Why it matters** | Deployment timing validation requires knowing which commit was deployed. Without it, "was commit deployed before incident?" cannot be answered. |
| **Severity** | Blocker |
| **Remediation** | Reject Deployment until commit is known; or quarantine and exclude from correlation. |

---

### I4. Every RCA_ATTRIBUTED target has HAS_FRAME from same Anomaly

| | |
|---|---|
| **Statement** | For every Anomaly -[:RCA_ATTRIBUTED]-> StackFrame, there exists Anomaly -[:HAS_FRAME]-> that same StackFrame. |
| **Why it matters** | Attribution must reference a frame in the anomaly's trace. Otherwise the attribution is invalid. |
| **Severity** | Blocker |
| **Remediation** | Reject RCA_ATTRIBUTED if target not in trace; or delete invalid attribution. |

---

## Ambiguous Mapping

### I5. At most one TOUCHED per (Commit, File) pair

| | |
|---|---|
| **Statement** | For any Commit and File, there exists at most one TOUCHED relationship from Commit to File. |
| **Why it matters** | Duplicate TOUCHED causes ambiguous "last modified" queries and inflated counts. |
| **Severity** | Degrade |
| **Remediation** | Deduplicate on ingestion; merge or delete duplicate TOUCHED. |

---

### I6. frame_order is unique per Anomaly

| | |
|---|---|
| **Statement** | For each Anomaly, all HAS_FRAME edges have distinct frame_order values. |
| **Why it matters** | Ambiguous frame order breaks deterministic stack traversal and top-frame selection. |
| **Severity** | Blocker |
| **Remediation** | Recompute frame_order from trace; reject ingestion if order cannot be determined. |

---

### I7. frame_order is contiguous (0 to n−1)

| | |
|---|---|
| **Statement** | For each Anomaly with n HAS_FRAME edges, frame_order values are exactly 0, 1, …, n−1. |
| **Why it matters** | Gaps or out-of-range values make top-frame and depth signals undefined. |
| **Severity** | Degrade |
| **Remediation** | Renumber frame_order to remove gaps; drop frames that cannot be ordered. |

---

## Duplicate Accepted RCA

### I8. At most one non-superseded RCA_ATTRIBUTED per Anomaly

| | |
|---|---|
| **Statement** | For each Anomaly, at most one RCA_ATTRIBUTED has status in {candidate, accepted} (i.e., not superseded or rejected). |
| **Why it matters** | Multiple "current" attributions make RCA non-deterministic; which root cause is correct? |
| **Severity** | Blocker |
| **Remediation** | Set older attributions to superseded when new one is created; or reject new attribution until conflict resolved. |

---

### I9. At most one RCA_ATTRIBUTED with status=accepted per Anomaly

| | |
|---|---|
| **Statement** | For each Anomaly, at most one RCA_ATTRIBUTED has status = accepted. |
| **Why it matters** | Accepted is the confirmed root cause. Duplicate accepted = ambiguous resolution. |
| **Severity** | Blocker |
| **Remediation** | Set duplicate accepted to superseded; keep only the latest by attributed_at. |

---

## Inconsistent service_ref

### I10. Deployment and Anomaly share service_ref when correlated

| | |
|---|---|
| **Statement** | When correlating Anomaly to Deployment for timing validation, Deployment.service_ref must equal Anomaly.service_ref. |
| **Why it matters** | Wrong-service deployment would produce false "deployed before incident" results. |
| **Severity** | Blocker |
| **Remediation** | Filter by service_ref in correlation queries; reject cross-service correlation. |

---

### I11. Deployment and Commit are for same logical service

| | |
|---|---|
| **Statement** | For Deployment -[:DEPLOYED_COMMIT]-> Commit, the Commit must belong to the same service (via repo_ref or service_ref scope). |
| **Why it matters** | Deploying a commit from another service invalidates deployment timing for this service. |
| **Severity** | Blocker |
| **Remediation** | Validate repo/service scope on DEPLOYED_COMMIT creation; reject if mismatch. |

---

## Timestamp Anomalies

### I12. Anomaly has timestamp

| | |
|---|---|
| **Statement** | Every Anomaly node has a non-null timestamp property. |
| **Why it matters** | Time-range queries and deployment timing comparison require anomaly time. |
| **Severity** | Blocker |
| **Remediation** | Reject Anomaly without timestamp; or backfill from window_id if derivable. |

---

### I13. Deployment has timestamp

| | |
|---|---|
| **Statement** | Every Deployment node has a non-null timestamp property. |
| **Why it matters** | "Was commit deployed before incident?" requires deployment time. |
| **Severity** | Blocker |
| **Remediation** | Reject Deployment without timestamp; or backfill from deployment system. |

---

### I14. Deployment timestamp precedes Anomaly timestamp when correlating

| | |
|---|---|
| **Statement** | For valid deployment–incident correlation, Deployment.timestamp < Anomaly.timestamp. |
| **Why it matters** | A deployment after the incident cannot have caused it. |
| **Severity** | Degrade |
| **Remediation** | Exclude post-incident deployments from correlation; flag if only such deployments exist. |

---

### I15. Commit has timestamp

| | |
|---|---|
| **Statement** | Every Commit node has a non-null timestamp property. |
| **Why it matters** | "Last modified" ordering requires commit time. |
| **Severity** | Blocker |
| **Remediation** | Reject Commit without timestamp; or backfill from git. |

---

### I16. RCA_ATTRIBUTED has attributed_at

| | |
|---|---|
| **Statement** | Every RCA_ATTRIBUTED edge has a non-null attributed_at property. |
| **Why it matters** | Resolving current vs superseded attribution requires ordering. |
| **Severity** | Blocker |
| **Remediation** | Reject RCA_ATTRIBUTED without attributed_at; backfill with ingestion time if acceptable. |

---

## Orphan Nodes

### I17. No StackFrame without incoming HAS_FRAME

| | |
|---|---|
| **Statement** | Every StackFrame has at least one incoming HAS_FRAME from some Anomaly. |
| **Why it matters** | Orphan frames are unreachable from anomalies; they consume storage and can cause phantom joins. |
| **Severity** | Warn |
| **Remediation** | Periodic cleanup of orphan StackFrames; or link to Anomaly if trace can be recovered. |

---

### I18. No File without IN_FILE or TOUCHED

| | |
|---|---|
| **Statement** | Every File has at least one incoming IN_FILE or at least one incoming TOUCHED. |
| **Why it matters** | Orphan files are unreachable; they add noise and storage. |
| **Severity** | Warn |
| **Remediation** | Periodic cleanup of orphan Files; or retain if expected for future commits. |

---

### I19. No Commit without TOUCHED

| | |
|---|---|
| **Statement** | Every Commit has at least one outgoing TOUCHED to a File. |
| **Why it matters** | Empty commits cannot be correlated to code; "last modified" is undefined. |
| **Severity** | Degrade |
| **Remediation** | Exclude from "last modified" queries; or backfill TOUCHED from git diff. |

---

## Summary by Severity

| Severity | Count | Invariants |
|----------|-------|------------|
| Blocker | 12 | I1–I4, I6, I8, I9, I10, I11, I12, I13, I15, I16 |
| Degrade | 5 | I5, I7, I14, I19 |
| Warn | 2 | I17, I18 |
