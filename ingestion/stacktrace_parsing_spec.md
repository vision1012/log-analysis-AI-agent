# Stacktrace Parsing Spec — Deterministic Rules

Deterministic parsing rules for stacktraces across Java, Python, Node, Go. Extracts symbol_name, file_path, line_number, frame_order; generates trace_ref; handles unresolved frames.

---

## 1. Input and Output

### Input

- Raw stacktrace text (from logs, exceptions, error reports)
- Language hint (java, python, node, go) or auto-detect from format

### Output (Per Frame)

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| symbol_name | string | Yes | Function/method name for fingerprint and RCA |
| file_path | string | Yes (or placeholder) | Repo-relative path for IN_FILE resolution |
| line_number | integer | No | Display only; excluded from trace_ref |
| frame_order | integer | Yes | Position in stack (0 = top) |
| resolution | enum | Yes | `resolved` or `unknown` |

### Output (Per Trace)

| Field | Type | Purpose |
|-------|------|---------|
| trace_ref | string | 32 hex chars; stable fingerprint for given parser_version |
| frames | array | Ordered list of parsed frames |
| parser_version | string | Version of parser that produced this output (e.g. semver 1.0.0) |
| schema_version | string | Contract version of parsing output format (e.g. semver 1.0.0) |

---

## 2. Language-Specific Extraction Rules

### Java / JVM

**Format:** `at fully.qualified.Class.method(SourceFile.java:line)` or `at fully.qualified.Class.method(SourceFile.java)` or `at Class.method(Unknown Source)`

| Field | Extraction Rule |
|-------|-----------------|
| symbol_name | Extract `fully.qualified.Class.method` or `Class.method`; strip `(SourceFile.java:line)` suffix. Use ` fully.qualified.Class.method` as-is. If "Unknown Source" or "Native Method", use `<unknown>`. |
| file_path | Derive from class: `fully/qualified/Class.java` (replace `.` with `/`, append `.java`). Or extract from `SourceFile.java` if present. If "Unknown Source", use placeholder. |
| line_number | Extract from `:line` if present; else null. |
| frame_order | 0 for first `at ` line; increment for each subsequent. |

**Edge cases:** `$` in class name (inner class); `lambda$`; `Native Method` → resolution=unknown.

---

### Python

**Format:** `File "path", line N, in function` or `File "path", line N, in <module>` or `  File "path", line N, in function`

| Field | Extraction Rule |
|-------|-----------------|
| symbol_name | Extract `function` or `<module>`. If `<module>`, use module name from path if available (e.g. `mymodule` from `mymodule.py`). |
| file_path | Extract path from `"path"`; normalize to repo-relative (strip prefixes). |
| line_number | Extract N from `line N`. |
| frame_order | 0 for first `File "`; increment for each subsequent. |

**Edge cases:** `<>` in path; `site-packages`, `lib/python` → stdlib; can mark resolution=unknown for non-repo paths.

---

### Node / JavaScript

**Format:** `at function (path:line:col)` or `at Object.method (path:line:col)` or `at async function (path:line:col)`

| Field | Extraction Rule |
|-------|-----------------|
| symbol_name | Extract `function`, `Object.method`, or `async function`. Preserve `Object.method` for methods. |
| file_path | Extract path from `(path:line:col)`; normalize separators; strip `file://` if present. |
| line_number | Extract from `:line:`; else null. |
| frame_order | 0 for first `at `; increment for each subsequent. |

**Edge cases:** `node:internal`; `node_modules` → resolution=unknown for non-app code if desired.

---

### Go

**Format:** `path:line +0xoffset` or `created by package.function` or `goroutine N [state]: package.function(path:line +0xoffset)`

| Field | Extraction Rule |
|-------|-----------------|
| symbol_name | Extract `package.function` or `package.(*Type).method`. Strip `created by ` prefix. |
| file_path | Extract path from `path:line`; use full path; normalize to repo-relative. |
| line_number | Extract from `:line`; else null. |
| frame_order | 0 for first frame in goroutine; increment. Multiple goroutines: treat each as separate trace or concatenate with goroutine order. |

**Edge cases:** `runtime.`; `vendor/` paths; `C.go` (cgo) → resolution=unknown for stdlib/vendor if not in repo.

---

## 3. trace_ref Generation (Fingerprint Rules)

Reference: graph design for trace_ref. Goal: dedupe + join stability across runs.

### Per-Frame Fingerprint

1. **Normalize symbol:** Strip line/path suffixes; use `<unknown>` if empty.
2. **Normalize path:** Repo-relative; `/` separators; lowercase if case-insensitive FS; strip `node_modules/`, `__pycache__/`, build dirs; collapse `./`, `//`.
3. **Exclude line_number** from fingerprint.
4. **Compute:** `frame_fp = hash(symbol_normalized + "|" + path_normalized)` (e.g. SHA-256 truncated to 16 hex chars).

### Trace Fingerprint

1. **Order:** Frames in stack order (top = 0).
2. **Compute:** `trace_ref = hash(frame_fp_0 + ";" + frame_fp_1 + ";" + ... + frame_fp_n)` truncated to 32 hex chars.
3. **Determinism:** Same hash function, encoding (UTF-8), no randomness.

### Unresolved Frames in Fingerprint

- Include unresolved frames in trace_ref (use placeholder path e.g. `<unresolved>` for path_normalized).
- Ensures same logical trace produces same trace_ref even when some frames are unresolved.

### parser_version and schema_version

| Field | Purpose |
|-------|---------|
| **parser_version** | Identifies the parser/rules that produced trace_ref. Same trace + same parser_version → same trace_ref. When parser changes (normalization, extraction rules), trace_ref may change for same raw trace. |
| **schema_version** | Contract version of the parsing output (fields, structure). Enables forward compatibility; reject or migrate when incompatible. |

**Storage:** parser_version and schema_version stored on Anomaly (and optionally StackFrame) for audit and mismatch resolution.

---

## 4. Unresolved Frames (resolution=unknown)

### When to Mark resolution=unknown

| Condition | resolution |
|-----------|------------|
| file_path not in repo (stdlib, node_modules, vendor, etc.) | unknown |
| file_path cannot be parsed | unknown |
| symbol_name cannot be parsed (use `<unknown>`) | unknown |
| File node does not exist and cannot be created (path outside repo scope) | unknown |
| "Unknown Source", "Native Method", "internal" | unknown |

### Graph Handling (No Sentinel)

**Rule:** Do not create a shared sentinel File. Unresolved frames do not pollute the graph with synthetic nodes.

| Action | Description |
|--------|-------------|
| **Create StackFrame** | Create StackFrame for all frames (resolved and unresolved). Preserves frame_order and trace structure. |
| **IN_FILE** | Create IN_FILE only when resolution=resolved. Unresolved StackFrames have no IN_FILE. |
| **resolution property** | StackFrame.resolution = `resolved` or `unknown`. |

### Degrade vs Block

| Condition | RCA Impact |
|-----------|------------|
| **Partial trace** | At least one frame has IN_FILE; at least one lacks IN_FILE. **Degrade** — RCA proceeds with resolved frames only; confidence lowered. |
| **Entire trace unresolved** | All frames lack IN_FILE. **Block** — No function-level RCA possible; reject or quarantine anomaly. |

### StackFrame Identity (Deterministic)

```
stackframe_id = hash(trace_ref + "|" + frame_order + "|" + symbol_name + "|" + normalized_path)
```

| Aspect | Rule |
|--------|------|
| **Hash** | SHA-256 truncated to 32 hex chars (lowercase) |
| **Encoding** | UTF-8 |
| **normalized_path** | Repo-relative; `/` separators; collapse `//`; strip `./`; use `<unresolved>` when resolution=unknown |
| **symbol_name** | Use `<unknown>` when empty or unparseable |
| **frame_order** | Integer as string (e.g. `"0"`, `"1"`) |
| **Immutability** | stackframe_id never changes once assigned |

### Property on StackFrame

| Property | Values | Purpose |
|----------|--------|---------|
| resolution | `resolved`, `unknown` | Signals whether IN_FILE exists. Unresolved = no IN_FILE. |

---

## 5. What to Store in Graph vs Artifact Store

### Graph (Neo4j)

| Stored | Notes |
|--------|-------|
| Anomaly | id, timestamp, trace_ref, service_ref, window_id, parser_version, schema_version, etc. |
| StackFrame | id, trace_ref, symbol_name, frame_order, resolution |
| HAS_FRAME | Anomaly→StackFrame with frame_order |
| IN_FILE | StackFrame→File (only when resolution=resolved; no sentinel) |
| File | path, repo_ref (no sentinel; unresolved frames have no IN_FILE) |

**Not stored in graph:** Raw stacktrace text, line_number (optional; can store for display but not in fingerprint).

### Artifact Store

| Stored | Purpose |
|--------|---------|
| Raw stacktrace text | Audit, evidence, reproduction |
| Full frame list (symbol, path, line, order) | Evidence bundle; display |
| anomaly_id → artifact_ref | Link graph to artifact for evidence_ref |

**evidence_ref** on RCA_ATTRIBUTED points to artifact (bundle_id); artifact contains full trace for audit.

---

## 6. Determinism Checklist

| Rule | Required |
|------|----------|
| Same hash function and encoding | Yes |
| Line numbers excluded from trace_ref | Yes |
| Path normalization deterministic | Yes |
| Frame order stable (top to bottom) | Yes |
| Language detection deterministic | Yes (prefer explicit hint over heuristics) |
| Unresolved placeholder consistent | Yes (`<unresolved>` for path, `<unknown>` for symbol) |
| parser_version recorded | Yes |
| schema_version recorded | Yes |

---

## 7. trace_ref Mismatch: Block vs Quarantine

| Condition | Action | Rationale |
|-----------|--------|-----------|
| **Computed ≠ provided, same parser_version** | **Block** | Deterministic error; parser produced different fingerprint for same input. Reject; fix parser or input. |
| **Computed ≠ provided, parser_version differs** | **Quarantine** | Parser upgrade may change normalization; trace_ref can legitimately differ. Isolate; re-parse with current parser or retain for audit. |
| **schema_version incompatible** | **Quarantine** | Output format changed; cannot safely interpret. Isolate until migration or re-ingest. |
| **parser_version missing** | **Quarantine** | Cannot determine if mismatch is expected. Isolate for review. |

**Quarantine:** Anomaly and frames not promoted to "ingested"; excluded from RCA; retained for manual review or re-ingest with current parser.

---

## 8. Summary

| Aspect | Rule |
|--------|------|
| **symbol_name** | Extract per language; strip suffixes; use `<unknown>` if empty |
| **file_path** | Repo-relative; normalized; placeholder if unresolved |
| **line_number** | Extract if present; exclude from trace_ref |
| **frame_order** | 0 = top; increment down stack |
| **trace_ref** | hash of per-frame fingerprints (symbol+path, no line); 32 hex chars; stable for given parser_version |
| **parser_version / schema_version** | Record on Anomaly; used for block vs quarantine on trace_ref mismatch |
| **resolution=unknown** | When path not in repo or unparseable; no IN_FILE; no sentinel |
| **Graph** | Anomaly, StackFrame, HAS_FRAME, IN_FILE; parser_version, schema_version; no raw trace |
| **Artifact** | Raw trace, full frame list, parser_version; evidence_ref points here |
