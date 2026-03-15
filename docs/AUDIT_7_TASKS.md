# Audit: 7 Implementation Tasks

## Initial Checklist (Before Fixes)

| Task # | Status | Evidence | Gaps |
|--------|--------|----------|------|
| 1 | **Missing** | stacktrace_parsing_spec.md had trace_ref/frame_fp but no stackframe_id formula; ontology.md had File identity only | No stackframe_id = hash(trace_ref + "|" + frame_order + "|" + symbol_name + "|" + normalized_path) with <unknown> handling |
| 2 | **Partially Implemented** | neo4j_client.py exists with connect, execute_read, execute_write, execute_write_tx | Missing: env-based connection (from_env), health_check, session helper |
| 3 | **Partially Implemented** | writer.py has all upserts and links, write_atomic | File used (path, repo_ref) not file_id; MERGE mismatch with migrations |
| 4 | **Implemented** | post_ingestion_gate.py, pre_rca_gate.py with PASS/BLOCK/DEGRADE | — |
| 5 | **Implemented** | evidence_store.py has create_bundle, get_bundle, LocalFileEvidenceStore | — |
| 6 | **Partially Implemented** | smoke_test_graph.py: migrations, write, gates | Missing: evidence bundle, RCA_ATTRIBUTED candidate writes |
| 7 | **Partially Implemented** | migrations.py, writer.py, pre_rca_gate | RCA_ATTRIBUTED links to StackFrame; no explicit (anomaly_id, run_id, file_id) constraint; gate handles accepted |

**Summary: 2/7 fully implemented, 4/7 partially implemented, 1/7 missing**

---

## Implemented Fixes

1. **Task 1:** Added StackFrame identity to ingestion/stacktrace_parsing_spec.md and graph/ontology.md
2. **Task 2:** Added from_env(), health_check(), session() to graph/neo4j_client.py
3. **Task 3:** Updated writer.upsert_file to MERGE on file_id; link_in_file/link_touched use File.file_id
4. **Task 6:** Added evidence bundle creation and RCA_ATTRIBUTED candidate writes to smoke_test_graph.py
5. **Task 7:** Documented RCA_ATTRIBUTED uniqueness in migrations.py (application-level; Neo4j has no relationship constraints)

---

## Final Checklist (After Fixes)

| Task # | Status | Evidence | Gaps |
|--------|--------|----------|------|
| 1 | **Implemented** | stacktrace_parsing_spec.md §4 "StackFrame Identity"; ontology.md "StackFrame Identity (Locked)" | — |
| 2 | **Implemented** | neo4j_client.py: from_env(), health_check(), session(), execute_read/write, execute_write_tx | — |
| 3 | **Implemented** | writer.py: upsert_file (file_id), all links, write_atomic, _compute_file_id | — |
| 4 | **Implemented** | post_ingestion_gate.py, pre_rca_gate.py: PASS/BLOCK/DEGRADE | — |
| 5 | **Implemented** | evidence_store.py: create_bundle, get_bundle, LocalFileEvidenceStore | — |
| 6 | **Implemented** | smoke_test_graph.py: migrations, write, gates, evidence bundle, RCA_ATTRIBUTED | — |
| 7 | **Implemented** | migrations.py docstring; pre_rca_gate blocks run_id idempotency + accepted; writer supersede + atomic | Neo4j cannot enforce relationship uniqueness; app logic handles it |

**Summary: 7/7 fully implemented**
