# Data Quality — Post-Ingestion Checks

Post-ingestion checks required to keep RCA deterministic. Run after each ingestion batch or on a schedule.

---

## 1. Missing Edges

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| Anomaly without frames | Anomaly has no outgoing HAS_FRAME | Cannot perform function-level RCA; anomaly is unusable. |
| StackFrame without IN_FILE (partial) | Some StackFrames have no IN_FILE (resolution=unknown) | Resolved frames usable; unresolved excluded from commit correlation. Degrade. |
| Entire trace unresolved | All StackFrames lack IN_FILE | Cannot traverse to File → Commit; block. |
| Deployment without commit | Deployment has no outgoing DEPLOYED_COMMIT | Cannot validate deployment timing; deployment uncorrelatable. |
| Orphan StackFrame | StackFrame has no incoming HAS_FRAME | Frame not linked to any anomaly; trace incomplete. |
| Commit without TOUCHED | Commit has no outgoing TOUCHED | Git mining incomplete; commit cannot be correlated to files. |

---

## 2. Unresolved Frames

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| IN_FILE target missing (resolved frame) | StackFrame with resolution=resolved has IN_FILE to non-existent File | Broken traversal; fix. |
| file_id mismatch | StackFrame.file_id does not match IN_FILE target | Inconsistent join; wrong file in RCA path. |

---

## 3. Trace Consistency

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| trace_ref mismatch | Anomaly.trace_ref ≠ StackFrame.trace_ref for HAS_FRAME | Join instability; same trace_ref rule violated. |
| frame_order gaps | frame_order has gaps or duplicates per Anomaly | Non-deterministic stack ordering. |
| frame_order range | frame_order not 0..n-1 for n frames | Ambiguous stack order. |

---

## 4. RCA Attribution Integrity

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| RCA target not in trace | RCA_ATTRIBUTED target StackFrame not in HAS_FRAME for that Anomaly | Invalid attribution; audit trail broken. |
| Duplicate accepted RCA | Multiple RCA_ATTRIBUTED with status=accepted for same Anomaly | Non-deterministic; which root cause is current? |
| Duplicate current RCA | Multiple RCA_ATTRIBUTED with status in {candidate, accepted} and same latest attributed_at | Ambiguous current attribution. |
| Missing required props | RCA_ATTRIBUTED missing run_id, method, confidence, status, evidence_ref, attributed_at | Audit incomplete; cannot resolve or verify. |

---

## 5. Deployment Correlation

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| Deployment without DEPLOYED_COMMIT | Deployment has no DEPLOYED_COMMIT to Commit | Cannot answer "was commit deployed before incident?" |
| commit_sha mismatch | Deployment.commit_sha ≠ Commit.sha for DEPLOYED_COMMIT target | Wrong commit linked; timing validation invalid. |
| Deployment without timestamp | Deployment missing timestamp | Cannot compare to Anomaly.timestamp for time correlation. |

---

## 6. Service Consistency

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| Inconsistent service_ref | Anomaly.service_ref ≠ Deployment.service_ref when correlating same service | Wrong deployment linked to anomaly; false correlation. |
| service_ref null | Anomaly or Deployment missing service_ref when required | Cannot scope deployment timing to correct service. |

---

## 7. Repo and File Consistency

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| TOUCHED repo mismatch | Commit.repo_ref ≠ File.repo_ref for TOUCHED | Cross-repo link; Git mining invalid. |
| Duplicate TOUCHED | Multiple TOUCHED between same (Commit, File) pair | Redundant edges; query ambiguity. |

---

## 8. Temporal Consistency

| Check | Condition | Impact if Violated |
|-------|-----------|-------------------|
| Anomaly without timestamp | Anomaly missing timestamp | Cannot filter by time or compare to Deployment. |
| Commit without timestamp | Commit missing timestamp | Cannot order commits for "last modified." |
| Invalid timestamp format | timestamp not parseable or not UTC | Time-range queries fail; comparison undefined. |

---

## 9. Summary: Severity

| Severity | Checks | Action |
|----------|--------|--------|
| **Critical** | Missing edges, entire trace unresolved, RCA target not in trace, duplicate accepted RCA | Block RCA or quarantine affected anomalies. |
| **High** | trace_ref mismatch, frame_order violations, commit_sha mismatch, service_ref inconsistency | Fix or flag; may produce wrong RCA. |
| **Medium** | Partial trace (some frames unresolved) | Degrade; RCA proceeds with resolved frames. |
| **Medium** | Duplicate TOUCHED, missing timestamps | Degrade quality; fix in next ingestion. |
| **Low** | Orphan StackFrame, Commit without TOUCHED | Cleanup; does not break active RCA. |
