# Evidence Bundle Contract

Specification for the evidence bundle referenced by `RCA_ATTRIBUTED.evidence_ref`. Supports deterministic RCA reproduction without storing raw proprietary code.

---

## Purpose

The evidence bundle provides the minimal data required to:
1. Reproduce the RCA decision deterministically
2. Audit why a given file (and optionally frame) was attributed as root cause
3. Verify integrity via hashes without storing sensitive content

**Alignment:** RCA_ATTRIBUTED targets File. The evidence bundle supports both file-level and frame-level attribution.

---

## Required Fields (Max 12)

| Field | Type | Constraint | Purpose |
|-------|------|------------|---------|
| bundle_id | string | UUID or ULID; max 36 chars | Unique reference; equals evidence_ref on RCA_ATTRIBUTED |
| anomaly_id | string | Max 64 chars | Links to Anomaly node |
| trace_ref | string | 32 hex chars (SHA-256 truncated) | Trace fingerprint; matches trace_ref on Anomaly and StackFrames |
| rca_run_id | string | Max 64 chars | RCA run that produced this attribution |
| method | string | Enum: deterministic, heuristic, manual | Attribution method |
| attributed_file_id | string | Max 64 chars | File node id; target of RCA_ATTRIBUTED |
| evidence_symbol | string | Max 256 chars | Symbol (function/method name) used as evidence; from StackFrame.symbol_name when frame-level |
| last_touch_commit_sha | string | 40 chars (git SHA-1) or empty | Commit that last modified the file; empty if unresolved |
| signal_scores | object | Max 2 KB serialized | Map of signal name → score (0–1); required for reproduction |
| decision_timestamp | string | ISO 8601 UTC | When the attribution was made |
| schema_version | string | Semver, e.g. 1.0.0 | Contract version for forward compatibility |

---

## Optional Fields

| Field | Type | Constraint | Purpose |
|-------|------|------------|---------|
| attributed_frame_id | string | Max 64 chars | StackFrame node id when frame-level attribution available |
| deployment_id | string | Max 64 chars | Deployment node id if deployment correlation was used |
| snippet_hash | string | 64 hex chars (SHA-256) | Hash of code snippet around attributed line; verify without storing code |
| snippet_line_range | string | e.g. "42:45" | Line range of snippet (start:end); for display fetch only |
| redaction_manifest | array | Max 512 chars | List of redaction rules applied (e.g. ["pii", "secrets"]) |
| frame_order | integer | 0–n | Position in stack; redundant with graph but useful for standalone verification |
| window_id | string | Max 64 chars | Time window; for correlation context |
| rule_version | string | Max 32 chars | Version of deterministic rules used |

---

## Size and Token Constraints

### Storage Strategy

| Content Type | Storage | Max Size | Rationale |
|--------------|---------|----------|----------|
| Identifiers, timestamps, enums | Raw | Per field limit above | Needed for queries and display |
| Trace content | Hashed (trace_ref) | 32 chars | Full trace not stored; fingerprint only |
| Signal scores | Raw (JSON) | 2 KB | Small; required for reproduction |
| Code snippets | Never raw | — | Do not store proprietary code |
| Snippet verification | Hashed (snippet_hash) | 64 chars | Verify code at read time without storing |
| Log excerpts | Summarized or hashed | Max 1 KB per excerpt | Metadata + hash; raw only if redacted and < 500 chars |
| File paths | Raw | Max 512 chars | Metadata; no code content |

### Token Constraints (for LLM downstream)

- Evidence bundle summary for LLM context: max 500 tokens.
- If bundle is passed to LLM: use summarized form (identifiers, signal_scores, evidence_symbol, trace_ref); exclude raw snippets.

---

## Redaction Rules

### Mandatory Redaction (Before Storage)

| Content | Rule | Example |
|---------|------|---------|
| Secrets, API keys, tokens | Replace with `[REDACTED]` or hash | `password=***` |
| PII (emails, IPs, user IDs) | Hash or mask | `user_abc123` → `user_[HASH]` |
| Proprietary source code | Do not store; use snippet_hash only | — |
| Log message bodies | Redact secrets; store structure only | Keep template, redact variables |
| File paths | Allow; strip host-specific prefixes | `/app/src/foo.py` → `src/foo.py` |

### Redaction Manifest

When redaction is applied, populate `redaction_manifest` with applied rule IDs (e.g. `["pii", "secrets", "paths"]`). Enables audit of what was redacted.

### Verification After Redaction

- `snippet_hash` must be computed on redacted content if any snippet is stored (none by default).
- Hashes remain stable for same content; redaction changes content and thus hash.

---

## Deterministic Reproduction

### Required for Reproduction

1. **Inputs:** anomaly_id, trace_ref, attributed_file_id, evidence_symbol, last_touch_commit_sha, deployment_id (if used).
2. **Signals:** Full `signal_scores` map with exact values used.
3. **Method:** `method` (deterministic, heuristic, manual).
4. **Rule version:** `rule_version` (optional but recommended for deterministic).

### Reproduction Steps (Plain English)

1. Load Anomaly by anomaly_id; verify trace_ref matches.
2. Load File by attributed_file_id; verify RCA_ATTRIBUTED from Anomaly to this File (or StackFrame with IN_FILE to this File when attributed_frame_id present).
3. If attributed_frame_id present: load StackFrame; verify HAS_FRAME from Anomaly, IN_FILE to attributed_file_id, and symbol_name = evidence_symbol.
4. Load Commit by last_touch_commit_sha; verify TOUCHED to File.
5. If deployment_id present: load Deployment; verify DEPLOYED_COMMIT to Commit and timestamp < Anomaly.timestamp.
6. Recompute each signal in signal_scores using the same formulas and inputs.
7. Compare recomputed scores to stored signal_scores; must match within tolerance (e.g. 1e-6 for float).
8. Apply the decision rule for the given method: e.g. deterministic = weighted sum of signals > threshold; heuristic = rule-based selection.
9. Decision rule must select the same attributed_file_id (and attributed_frame_id if frame-level).

### Reproducibility Guarantee

If the graph state at reproduction time matches the state at attribution time (or is a superset), and signal_scores and rule_version are stored, the same attributed_file_id must be produced.

---

## evidence_ref Semantics

- `evidence_ref` on RCA_ATTRIBUTED = `bundle_id` of the evidence bundle.
- Bundle is stored in artifact store or blob storage; graph holds only the reference.
- Lookup: given evidence_ref, fetch bundle by ID; validate schema_version; use for audit or reproduction.

---

## Summary

| Aspect | Constraint |
|--------|------------|
| Required fields | 11 (≤12) |
| RCA target | File (attributed_file_id); attributed_frame_id optional for frame-level |
| evidence_symbol | Symbol used as evidence; from StackFrame when frame-level |
| Raw storage | Identifiers, timestamps, signal_scores, paths (metadata only) |
| Hashed storage | trace_ref, snippet_hash |
| No raw storage | Proprietary code, full logs, secrets |
| Redaction | Mandatory for PII, secrets; manifest required |
| Reproduction | signal_scores + method + rule_version + graph state → same attributed_file_id |
