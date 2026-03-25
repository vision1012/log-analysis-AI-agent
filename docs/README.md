# Documentation Index (RCA v2)

This docs directory is now centered on the graph-based RCA platform.

## Active Architecture Docs

- `architecture_overview.md` - current RCA v2 system architecture
- `FILE_STRUCTURE.md` - repository structure with active vs archived areas
- `AUDIT_7_TASKS.md` - implementation/audit status history

## Active RCA Specs

- `graph/` docs: ontology, invariants, quality gates, lifecycle, evidence bundle contract
- `rca_engine/` docs: deterministic RCA flow, signal/ranking policy, rerun policy
- `ingestion/` docs: contracts, ordering, idempotency, failure modes
- `feedback/confirmation_workflow.md` - candidate confirmation/rejection workflow
- `evaluation/rca_metrics.md` - RCA quality and coverage metrics

## API and Runtime Docs

- `run_functions_api.md` - current API surface for RCA and feedback endpoints
- `desktop_*` / `mobile_*` docs - product-facing UI concepts (non-runtime)

## Legacy Archive

Legacy log-agent/RAG/job-pipeline documentation has been archived in:

- `old_log_arch_v1/docs/`

Those archived docs are retained for historical context and are not the active architecture.

---

## Files in this directory (`docs/`)

| File | Purpose |
|------|---------|
| `architecture_overview.md` | High-level RCA v2 architecture. |
| `FILE_STRUCTURE.md` | Repository layout (active vs archived areas). |
| `AUDIT_7_TASKS.md` | Audit / task tracking history. |
| `ai_agent_implementation_roadmap.md` | Roadmap for AI agent features. |
| `run_functions_api.md` | API surface for `run_*` style functions and endpoints. |
| `desktop_ui_workflow.md` | Desktop UI workflow (product). |
| `desktop_ui_mockups.html` | Static HTML mockups. |
| `desktop_app_tech_stack_recommendations.md` | Tech stack notes for a desktop client. |
| `mobile_ui_design.md` | Mobile UI design notes. |
| `mobile_ui_mockups.html` | Static HTML mockups. |
