# Confidence Signals — RCA Scoring

Ten graph-derived signals used for deterministic RCA confidence scoring. All signals are computed via graph traversals only; no LLM or external APIs.

---

## Signal Definitions

| # | Signal | Range | Description | Graph Traversal |
|---|--------|-------|-------------|-----------------|
| 1 | **top_frame** | 0–1 | Frame is at top of stack (frame_order=0). Top frame is most likely failure point. | HAS_FRAME.frame_order = 0 |
| 2 | **frame_depth** | 0–1 | Inverse depth: closer to top = higher. 1 − (frame_order / max_order). | HAS_FRAME.frame_order, count of frames |
| 3 | **last_touch_recency** | 0–1 | How recently the file was modified before the anomaly. Closer commit timestamp to anomaly = higher. | File←IN_FILE←StackFrame; File←TOUCHED←Commit; max(Commit.timestamp) |
| 4 | **deploy_proximity** | 0–1 | Last-touch commit was deployed; deployment timestamp close to anomaly. Normalized time delta. | Deployment→DEPLOYED_COMMIT→Commit; Deployment.timestamp, Anomaly.timestamp |
| 5 | **deploy_recency_rank** | 0–1 | Last-touch commit's deployment is the most recent deployment before the anomaly. 1 if yes, 0 otherwise. | Deployments for service_ref, ordered by timestamp |
| 6 | **historical_recurrence** | 0–1 | Same file (or symbol) attributed in prior incidents for this service. Normalized count. | RCA_ATTRIBUTED→StackFrame→IN_FILE→File; prior anomalies with same service_ref |
| 7 | **trace_completeness** | 0–1 | Fraction of frames in trace with resolution=resolved. 1 if all resolved. | StackFrame.resolution per HAS_FRAME |
| 8 | **path_exclusion** | 0 or 1 | File path is application code (not vendor/stdlib). 1 if included, 0 if excluded. | File.path; match against exclusion patterns |
| 9 | **deployment_timing_valid** | 0 or 1 | Deployment timestamp < Anomaly timestamp. 1 if valid, 0 if missing or invalid. | Deployment.timestamp, Anomaly.timestamp |
| 10 | **file_frame_count** | 0–1 | How many frames in this trace point to this file. More frames = stronger signal. Normalized by trace length. | StackFrame→IN_FILE→File; count frames per file |

---

## Exclusion Patterns (path_exclusion)

| Pattern | Description |
|---------|-------------|
| `node_modules/` | Node.js dependencies |
| `vendor/` | Go, PHP vendor dirs |
| `site-packages/` | Python packages |
| `lib/python` | Python stdlib |
| `node:internal` | Node runtime |
| `runtime.` | Go runtime |
| `java.*` (stdlib) | JVM stdlib packages (e.g. `java.`, `sun.`, `jdk.`) |

**path_exclusion = 1** when File.path does not match any exclusion pattern. **path_exclusion = 0** when path matches (file excluded from candidates).

---

## Signal Computation (Graph Traversals)

All signals are computed from the graph. No external calls. Traversals:

- **Anomaly → HAS_FRAME → StackFrame** (with frame_order)
- **StackFrame → IN_FILE → File** (when resolution=resolved)
- **File ← TOUCHED ← Commit** (last touch: max timestamp)
- **Deployment → DEPLOYED_COMMIT → Commit**
- **Anomaly -[:RCA_ATTRIBUTED]-> StackFrame** (historical)

---

## Dependencies

| Signal | Requires |
|--------|----------|
| top_frame, frame_depth | HAS_FRAME, frame_order |
| last_touch_recency | IN_FILE, TOUCHED, Commit.timestamp |
| deploy_proximity, deploy_recency_rank, deployment_timing_valid | Deployment, DEPLOYED_COMMIT, service_ref match |
| historical_recurrence | Prior RCA_ATTRIBUTED edges |
| trace_completeness | StackFrame.resolution |
| path_exclusion | File.path |
| file_frame_count | IN_FILE, multiple frames per file |
