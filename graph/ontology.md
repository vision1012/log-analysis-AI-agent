# Knowledge Graph Ontology — Design Documentation

## Overview

This document defines the ontology for the Neo4j-based Knowledge Graph that extends the autonomous debugging system. The ontology describes the domain concepts, entity types, and semantic structure used to represent log analysis, debugging workflows, and incident knowledge.

## Scope

The ontology covers:

- **Log entities**: Log sources, templates, events, and structured log entries
- **Debugging artifacts**: Jobs, runs, anomalies, and investigation outputs
- **Temporal context**: Timestamps, windows, and event ordering
- **Semantic relationships**: To be defined in a later phase (see `models.md` for node definitions only)

## Design Principles

- **Minimal coupling**: The graph layer does not modify existing V1 modules (api, agent, utilities, machine_learning)
- **Extensibility**: Node types and properties are designed for future relationship modeling
- **Temporal awareness**: All time-sensitive entities support temporal modeling (see `time_model.md`)

## Domain Concepts

| Concept | Description |
|---------|-------------|
| LogSource | Origin of log data (file, stream, system) |
| LogTemplate | Parsed log template / pattern |
| LogEvent | Individual log line or structured event |
| Anomaly | Detected anomaly from ML or heuristics |
| Job | Debugging job / analysis run |
| Investigation | Investigation step or finding |

---

## File Identity (Locked)

File nodes use a deterministic, immutable identity. Aligns with `ingestion/git_mining_spec.md`.

### Formula

```
file_id = hash(repo_ref + "|" + canonical_repo_relative_path)
```

Where `canonical_repo_relative_path` is the **identity path** — the path at first creation, normalized. See canonical path rules below.

### Hash Function

| Aspect | Rule |
|--------|------|
| Algorithm | SHA-256 |
| Output | Truncated to 32 hex chars (first 16 bytes) |
| Encoding | UTF-8 for input string |
| Format | Lowercase hex string |

### Canonical Path Normalization

Apply before hashing and for all path comparisons:

| Rule | Description |
|------|-------------|
| Repo-relative | Path must be relative to repo root. Strip leading `./`, `/`, or repo root prefix. |
| Separator | Forward slash `/` only. Convert backslashes to forward slashes. |
| Collapse | Replace multiple consecutive slashes with one. |
| Trailing slash | Strip for files. Root `""` or `"/"` → `""`. |
| Whitespace | Trim leading and trailing whitespace. |
| Case | Preserve (paths are case-sensitive). |
| Unicode | Normalize to NFC. |

### Immutability

| Rule | Description |
|------|-------------|
| **file_id never changes** | Once assigned at creation, file_id is immutable for the lifetime of the File node. |
| Identity path | The path used to compute file_id (at first creation) is the identity path. Stored as `path` or `identity_path`. |
| Lookup | File is uniquely identified by file_id. Use path/canonical_path for human-facing lookup. |

### Renames and Identity Preservation

When a file is renamed (A → B):

| Property | Behavior |
|----------|----------|
| **file_id** | Unchanged. Identity preserved. |
| **path** (identity path) | Unchanged. Original path at creation. |
| **canonical_path** | Updated to B. Current path after rename. |
| **previous_paths** | Append A (or chain). Paths this logical file had before. |

Do **not** create a new File node for the new path. Update the existing File: set `canonical_path = B`, `previous_paths = [A, …]`. The same logical file keeps the same file_id across renames.

### Lookup by Path

Given a path P (e.g. from commit or stacktrace):

1. Normalize P to canonical form.
2. Compute `candidate_id = hash(repo_ref + "|" + canonical(P))`.
3. If File exists with `file_id = candidate_id`, match.
4. Else: lookup by `canonical_path = canonical(P)` or `path = canonical(P)` or `canonical(P) IN previous_paths` (for renamed files created before identity was adopted).

---

## Versioning

- **Version**: 1.0
- **Status**: Design phase — node definitions and constraints only; relationships deferred
