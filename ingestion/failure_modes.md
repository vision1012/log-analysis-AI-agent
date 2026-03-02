# Ingestion Failure Modes

Top ingestion failure cases with detect signal, gate impact, remediation, and RCA impact.

---

## Summary

| Failure | Detect | Gate | Remediation | RCA Impact |
|---------|--------|------|-------------|------------|
| Anomaly without frames | I1 | Post-ingestion, Pre-RCA | Reject or quarantine | **Blocks** |
| StackFrame without IN_FILE (partial trace) | I2 | Post-ingestion, Pre-RCA | Proceed with resolved frames; degrade | **Degrades** |
| Entire trace unresolved | I1, I2 | Post-ingestion, Pre-RCA | Reject or quarantine anomaly | **Blocks** |
| trace_ref mismatch (same parser_version) | Data quality | Post-ingestion | Block; fix parser | **Blocks** |
| trace_ref mismatch (parser/schema version) | Data quality | Post-ingestion | Quarantine; re-parse or migrate | **Quarantine** |
| frame_order gaps/duplicates | I6, I7 | Post-ingestion | Reject; fix ordering | **Blocks** |
| Deployment without DEPLOYED_COMMIT | I3 | Post-ingestion, Pre-RCA | Pending backfill; exclude from correlation | **Degrades** |
| Commit not found for deployment | — | Ingestion-time | backfill_status=pending | **Degrades** |
| Missing timestamps | I12, I13, I15 | Post-ingestion | Reject record | **Blocks** |
| Duplicate TOUCHED | I5 | Post-ingestion | Deduplicate | **Degrades** |
| Empty modified_files | I19 | Post-ingestion | Allow for merge; log | **Degrades** |
| service_ref inconsistency | I10, I11 | Pre-RCA | Exclude from correlation | **Degrades** |
| Duplicate accepted RCA | I8, I9 | Pre-RCA, Post-RCA | Supersede older | **Blocks** |
| Orphan StackFrame | I17 | Post-ingestion | Cleanup; log | **Warn** |
| Orphan File | I18 | Post-ingestion | Cleanup; log | **Warn** |
| TOUCHED repo mismatch | Data quality | Post-ingestion | Reject TOUCHED | **Blocks** |
| Clock skew | — | Query-time | Tolerance buffer; degrade confidence | **Degrades** |

---

## 1. Anomaly Without Frames

| | |
|---|---|
| **Detect signal** | Anomaly has no outgoing HAS_FRAME (I1) |
| **Gate impact** | Post-ingestion: fail batch. Pre-RCA: exclude anomaly from scope. |
| **Remediation** | Reject anomaly at ingestion; do not create. Or quarantine; exclude from RCA until trace available. |
| **RCA impact** | **Blocks** — Cannot run function-level RCA without frames. |

---

## 2. StackFrame Without IN_FILE (Partial Trace)

| | |
|---|---|
| **Detect signal** | At least one StackFrame has no outgoing IN_FILE (resolution=unknown); at least one has IN_FILE. |
| **Gate impact** | Post-ingestion: degrade batch. Pre-RCA: proceed; exclude unresolved frames from File→Commit traversal. |
| **Remediation** | Create StackFrame without IN_FILE; set resolution=unknown. RCA uses resolved frames only; lower confidence. |
| **RCA impact** | **Degrades** — Unresolved frames excluded from commit correlation; confidence lowered. |

---

## 3. Entire Trace Unresolved

| | |
|---|---|
| **Detect signal** | All StackFrames lack IN_FILE; or no frames resolve (File not found for any frame). |
| **Gate impact** | Post-ingestion: fail batch. Pre-RCA: exclude anomaly from scope. |
| **Remediation** | Reject anomaly; do not create. Or quarantine until trace can be resolved. Retry when Git sync adds Files. |
| **RCA impact** | **Blocks** — No function-level RCA possible; no frames with File→Commit path. |

---

## 4. trace_ref Mismatch

| | |
|---|---|
| **Detect signal** | Anomaly.trace_ref ≠ StackFrame.trace_ref for HAS_FRAME; or computed trace_ref ≠ provided. |
| **Gate impact** | Post-ingestion: data quality check. |

### Block vs Quarantine

| Condition | Action | RCA Impact |
|-----------|--------|------------|
| **Computed ≠ provided, same parser_version** | **Block** — Reject anomaly; deterministic parser error. | **Blocks** |
| **Computed ≠ provided, parser_version differs** | **Quarantine** — Isolate; re-parse with current parser or retain for audit. | **Quarantine** — Excluded from RCA until resolved. |
| **schema_version incompatible** | **Quarantine** — Cannot interpret output; isolate for migration. | **Quarantine** |
| **parser_version missing** | **Quarantine** — Cannot determine cause; isolate for review. | **Quarantine** |

**Remediation:** Block: fix parser or input. Quarantine: re-ingest with current parser_version; or migrate schema; or manual review.

---

## 5. frame_order Gaps or Duplicates

| | |
|---|---|
| **Detect signal** | frame_order not unique (I6) or not contiguous 0..n−1 (I7). |
| **Gate impact** | Post-ingestion: fail batch. |
| **Remediation** | Reject anomaly; fix frame ordering in parser. Renumber if gaps only (degrade path). |
| **RCA impact** | **Blocks** — Non-deterministic stack order; top-frame undefined. |

---

## 6. Deployment Without DEPLOYED_COMMIT

| | |
|---|---|
| **Detect signal** | Deployment has no outgoing DEPLOYED_COMMIT (I3); backfill_status=pending. |
| **Gate impact** | Post-ingestion: fail if I3 is blocker; or pass with degrade. Pre-RCA: exclude from correlation scope. |
| **Remediation** | Create Deployment with backfill_status=pending. Backfill job adds DEPLOYED_COMMIT when commit list arrives. Exclude from deployment correlation until complete. |
| **RCA impact** | **Degrades** — Deployment timing validation unavailable; deploy signals = 0. RCA proceeds with other signals. |

---

## 7. Commit Not Found for Deployment

| | |
|---|---|
| **Detect signal** | Lookup Commit(repo_ref, commit_sha) returns nothing. |
| **Gate impact** | Ingestion-time; Deployment created with pending. |
| **Remediation** | Create Deployment; set backfill_status=pending. When Git sync adds Commit, backfill job creates DEPLOYED_COMMIT. |
| **RCA impact** | **Degrades** — Same as Deployment without DEPLOYED_COMMIT. |

---

## 8. Missing Timestamps

| | |
|---|---|
| **Detect signal** | Anomaly, Deployment, or Commit missing timestamp (I12, I13, I15). |
| **Gate impact** | Post-ingestion: fail batch for affected entities. |
| **Remediation** | Reject record at ingestion. Backfill from source if possible. |
| **RCA impact** | **Blocks** — Cannot filter by time or compare Deployment to Anomaly. |

---

## 9. Duplicate TOUCHED

| | |
|---|---|
| **Detect signal** | Multiple TOUCHED between same (Commit, File) pair (I5). |
| **Gate impact** | Post-ingestion: degrade; deduplicate. |
| **Remediation** | Deduplicate on ingestion; merge or delete duplicate edges. Log. |
| **RCA impact** | **Degrades** — Inflated counts; ambiguous "last modified." Fix in next ingestion. |

---

## 10. Empty modified_files (Commit)

| | |
|---|---|
| **Detect signal** | Commit has no outgoing TOUCHED (I19). |
| **Gate impact** | Post-ingestion: degrade. |
| **Remediation** | Allow for merge commits with no file changes; log. Exclude from "last modified" queries. |
| **RCA impact** | **Degrades** — Commit cannot be correlated to files; "last modified" may miss. |

---

## 11. service_ref Inconsistency

| | |
|---|---|
| **Detect signal** | Anomaly.service_ref ≠ Deployment.service_ref when correlating; or Deployment–Commit scope mismatch (I10, I11). |
| **Gate impact** | Pre-RCA: exclude deployments from correlation. |
| **Remediation** | Filter by service_ref in correlation queries; reject cross-service links. Fix service_ref mapping. |
| **RCA impact** | **Degrades** — Wrong deployment linked; exclude from correlation; lower confidence for affected anomalies. |

---

## 12. Duplicate Accepted RCA

| | |
|---|---|
| **Detect signal** | Multiple RCA_ATTRIBUTED with status=accepted for same Anomaly (I9); or multiple with status in {candidate, accepted} (I8). |
| **Gate impact** | Pre-RCA: exclude anomaly. Post-RCA: block write. |
| **Remediation** | Supersede older attributions when new one written. Manual fix: demote duplicates to superseded; keep latest by attributed_at. |
| **RCA impact** | **Blocks** — Non-deterministic; which root cause is current? Must resolve before RCA. |

---

## 13. Orphan StackFrame

| | |
|---|---|
| **Detect signal** | StackFrame has no incoming HAS_FRAME (I17). |
| **Gate impact** | Post-ingestion: warn; batch passes. |
| **Remediation** | Periodic cleanup of orphan StackFrames. Log for investigation. |
| **RCA impact** | **Warn** — Does not break active RCA; cleanup only. |

---

## 14. Orphan File

| | |
|---|---|
| **Detect signal** | File has no incoming IN_FILE or TOUCHED (I18). |
| **Gate impact** | Post-ingestion: warn; batch passes. |
| **Remediation** | Periodic cleanup. Retain if expected for future commits. |
| **RCA impact** | **Warn** — Does not break active RCA. |

---

## 15. TOUCHED Repo Mismatch

| | |
|---|---|
| **Detect signal** | Commit.repo_ref ≠ File.repo_ref for TOUCHED. |
| **Gate impact** | Post-ingestion: data quality check. |
| **Remediation** | Reject TOUCHED at ingestion; fix repo_ref assignment. |
| **RCA impact** | **Blocks** — Cross-repo link invalid; Git mining wrong. |

---

## 16. Clock Skew

| | |
|---|---|
| **Detect signal** | Deployment.timestamp and Anomaly.timestamp from different sources; correlation may be wrong when timestamps are close. |
| **Gate impact** | Query-time; not an ingestion gate. |
| **Remediation** | Use tolerance buffer (e.g. 60s) for "deployed before incident." Degrade confidence when within buffer. |
| **RCA impact** | **Degrades** — Deploy proximity signal less reliable; lower confidence when timestamps close. |

---

## Block vs Degrade vs Quarantine vs Warn

| Level | Meaning |
|-------|---------|
| **Blocks** | RCA cannot run for affected scope, or result would be invalid. Reject at ingestion; must fix before RCA. |
| **Degrades** | RCA runs; confidence lower; some signals unavailable or unreliable. |
| **Quarantine** | Data isolated; not promoted to "ingested"; excluded from RCA. Retained for re-parse, migration, or manual review. |
| **Warn** | No RCA impact; log for cleanup or audit. |
