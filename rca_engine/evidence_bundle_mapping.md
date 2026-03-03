# Evidence Bundle Mapping — Deterministic RCA

For each field in `graph/evidence_bundle_contract.md`, this document describes how deterministic RCA populates it and from where in the graph it is derived.

**Alignment:** RCA attribution targets File. `attributed_file_id` is required. Frame-level evidence (`attributed_frame_id`, `evidence_symbol`) is optional but populated by deterministic RCA when a representative frame exists.

---

## Required Fields

### bundle_id

| | |
|---|---|
| **How populated** | Generated at write time. New UUID or ULID. |
| **Graph source** | None. Synthetic identifier. |
| **Purpose** | Unique reference; equals `evidence_ref` on RCA_ATTRIBUTED. |
| **Deterministic RCA** | One bundle per RCA_ATTRIBUTED edge. Each of up to 3 attributions gets its own bundle_id. |

---

### anomaly_id

| | |
|---|---|
| **How populated** | Copied from the Anomaly being attributed. |
| **Graph source** | `Anomaly.id` |
| **Traversal** | Start node of RCA run. |
| **Deterministic RCA** | The Anomaly that was the input to the RCA run. |

---

### trace_ref

| | |
|---|---|
| **How populated** | Copied from the Anomaly. |
| **Graph source** | `Anomaly.trace_ref` |
| **Traversal** | Anomaly node property. |
| **Deterministic RCA** | Fingerprint of the stack trace; matches trace_ref on Anomaly and all StackFrames in the trace. |

---

### rca_run_id

| | |
|---|---|
| **How populated** | From the RCA run context. |
| **Graph source** | Stored on RCA_ATTRIBUTED as `run_id`; not a graph node. |
| **Deterministic RCA** | The run_id assigned when the RCA run started. Links bundle to the run that produced it. |

---

### method

| | |
|---|---|
| **How populated** | Fixed value. |
| **Graph source** | None. |
| **Deterministic RCA** | Always `deterministic`. |

---

### attributed_file_id

| | |
|---|---|
| **How populated** | The File node id of the attributed file (winning candidate). |
| **Graph source** | `File.id` |
| **Traversal** | Anomaly → HAS_FRAME → StackFrame → IN_FILE → File. The File that was selected as root cause. |
| **Deterministic RCA** | Required. The File from the top-N ranked candidates (up to 3). Each bundle corresponds to one attributed File. |
| **Alignment** | **Primary target.** RCA attribution targets File; this field is always populated. |

---

### evidence_symbol

| | |
|---|---|
| **How populated** | From the representative StackFrame for the attributed File. |
| **Graph source** | `StackFrame.symbol_name` |
| **Traversal** | For the attributed File, the representative frame = StackFrame with smallest frame_order among frames that have IN_FILE to that File. |
| **Deterministic RCA** | Populated when representative frame exists (always, for deterministic RCA). Function/method name at the attributed stack position. |
| **Alignment** | Frame evidence; optional in contract. Deterministic RCA always has a representative frame, so always populates. |

---

### last_touch_commit_sha

| | |
|---|---|
| **How populated** | From the last Commit that touched the attributed File. |
| **Graph source** | `Commit.sha` |
| **Traversal** | File ← TOUCHED ← Commit. Select Commit with max(Commit.timestamp) where timestamp < Anomaly.timestamp. Per git_mining_spec: last-touch uses commits with TOUCHED only; merges without diffs excluded. |
| **Deterministic RCA** | Populated when File has at least one TOUCHED edge. Empty when File has no TOUCHED, or Commit not in graph (e.g. rebased/squashed). |

---

### signal_scores

| | |
|---|---|
| **How populated** | Map of 10 signal names to computed values (0–1 each). |
| **Graph source** | Derived from graph traversals (see confidence_signals.md). |
| **Traversal** | Each signal computed via: Anomaly→HAS_FRAME→StackFrame; StackFrame→IN_FILE→File; File←TOUCHED←Commit; Deployment→DEPLOYED_COMMIT→Commit; prior RCA_ATTRIBUTED. |
| **Deterministic RCA** | Required for reproduction. Keys: top_frame, frame_depth, last_touch_recency, deploy_proximity, deploy_recency_rank, historical_recurrence, trace_completeness, path_exclusion, deployment_timing_valid, file_frame_count. |

---

### decision_timestamp

| | |
|---|---|
| **How populated** | When the attribution was written. |
| **Graph source** | Same as RCA_ATTRIBUTED.attributed_at |
| **Deterministic RCA** | ISO 8601 UTC. Set at write time. |

---

### schema_version

| | |
|---|---|
| **How populated** | Bundle contract version. |
| **Graph source** | None. |
| **Deterministic RCA** | Semver, e.g. `1.0.0`. Identifies the evidence bundle schema for forward compatibility. |

---

## Optional Fields

### attributed_frame_id

| | |
|---|---|
| **How populated** | From the representative StackFrame for the attributed File. |
| **Graph source** | `StackFrame.id` |
| **Traversal** | Same as evidence_symbol: StackFrame with smallest frame_order among frames with IN_FILE to attributed File. |
| **Deterministic RCA** | Populated when frame-level attribution is available. Deterministic RCA always has a representative frame, so always populates. |
| **Alignment** | Frame evidence; optional. Enables verification: HAS_FRAME from Anomaly, IN_FILE to attributed_file_id. |

---

### deployment_id

| | |
|---|---|
| **How populated** | From the Deployment used for deployment correlation, when applicable. |
| **Graph source** | `Deployment.id` |
| **Traversal** | Deployment where Deployment.service_ref = Anomaly.service_ref, Deployment.timestamp < Anomaly.timestamp, and Deployment -[:DEPLOYED_COMMIT]-> Commit (last-touch Commit for attributed File). |
| **Deterministic RCA** | Populated when deploy_proximity, deploy_recency_rank, or deployment_timing_valid contributed (i.e. deployment correlation was used). Empty when no deployments, all pending, or service_ref mismatch. |

---

### snippet_hash

| | |
|---|---|
| **How populated** | Not populated by deterministic RCA. |
| **Graph source** | N/A |
| **Deterministic RCA** | No access to source code. Hash would require fetching file content; out of scope for graph-only RCA. |

---

### snippet_line_range

| | |
|---|---|
| **How populated** | Not populated by deterministic RCA. |
| **Graph source** | N/A |
| **Deterministic RCA** | Line numbers are display-only; not stored in graph (per stacktrace_parsing_spec). No code access. |

---

### redaction_manifest

| | |
|---|---|
| **How populated** | Not populated by deterministic RCA. |
| **Graph source** | N/A |
| **Deterministic RCA** | Applied at storage layer if redaction is performed. RCA does not redact. |

---

### frame_order

| | |
|---|---|
| **How populated** | From the representative StackFrame's position in the stack. |
| **Graph source** | `HAS_FRAME.frame_order` (or StackFrame position in trace) |
| **Traversal** | Representative frame = smallest frame_order among frames pointing to attributed File. |
| **Deterministic RCA** | Optional. Redundant with graph but useful for standalone verification. 0 = top of stack. |

---

### window_id

| | |
|---|---|
| **How populated** | From the Anomaly when available. |
| **Graph source** | `Anomaly.window_id` |
| **Traversal** | Anomaly node property. |
| **Deterministic RCA** | Optional. Time window for correlation context. |

---

### rule_version

| | |
|---|---|
| **How populated** | Fixed value for this engine. |
| **Graph source** | None. |
| **Deterministic RCA** | Always `deterministic_rca_v1`. Required for reproduction. |

---

## Gate Integration Fields (from gate_integration.md)

| Field | How Populated | Graph Source |
|-------|---------------|--------------|
| **gate_degradations** | When pre-RCA had degrade | Audit; e.g. I10_deployment_excluded, I2_partial_trace |
| **trace_completeness_note** | When partial trace | e.g. "3/5 frames resolved" |
| **deployment_correlation_note** | When deployments excluded | e.g. "2 deployments excluded for service_ref mismatch" |

---

## Summary: File vs Frame Alignment

| Aspect | Required | Optional |
|--------|----------|----------|
| **File-level** | attributed_file_id | — |
| **Frame-level** | — | attributed_frame_id, evidence_symbol, frame_order |
| **Deterministic RCA** | Always populates attributed_file_id | Always populates attributed_frame_id, evidence_symbol when representative frame exists |

**RCA attribution targets File.** The evidence bundle supports both:
- **File-only:** attributed_file_id required; frame fields may be omitted (e.g. heuristic or manual attribution).
- **File + frame:** attributed_file_id required; attributed_frame_id, evidence_symbol, frame_order optional. Deterministic RCA populates all when representative frame exists.
