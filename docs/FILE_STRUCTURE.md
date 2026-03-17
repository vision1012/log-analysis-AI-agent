# Log Analysis AI Agent – Complete File Structure

One-line description for each file.

---

## Root

| File | Description |
|------|-------------|
| `README.md` | Project overview, setup, and usage. |
| `README_dev.md` | Developer guide and contribution notes. |
| `requirements.txt` | Python dependencies (pydantic, fastapi, neo4j, etc.). |

---

## api/ — FastAPI backend

| File | Description |
|------|-------------|
| `api/__init__.py` | Package init. |
| `api/config.py` | Settings (Ollama model, paths, env vars). |
| `api/main.py` | FastAPI app entry; registers routers, middleware, CORS. |
| `api/EXAMPLE_CURL_COMMANDS.md` | Example curl commands for API endpoints. |
| `api/core/__init__.py` | Package init. |
| `api/core/paths.py` | Path constants (ARTIFACTS_DIR, OUTPUT_JOBS_DIR, RUNS_DIR). |
| `api/middleware/__init__.py` | Package init. |
| `api/middleware/observability.py` | Request/response logging, X-Request-Id header. |
| `api/routers/__init__.py` | Package init. |
| `api/routers/health.py` | Health check endpoint. |
| `api/routers/jobs.py` | Job CRUD, report, artifacts, cancel. |
| `api/routers/rca_routes.py` | RCA endpoints: run, rerun, results, result-view, run-status. |
| `api/routers/feedback_routes.py` | Feedback endpoints: confirm, reject, reject-all, rollback. |
| `api/schemas/__init__.py` | Package init. |
| `api/schemas/job.py` | Pydantic models for job requests/responses. |
| `api/services/__init__.py` | Package init. |
| `api/services/job_store.py` | In-memory job store (create, get, update, cancel). |
| `api/services/runner.py` | Job runner; executes pipeline (RAG/heuristic). |
| `api/services/rca_service.py` | RCA orchestration: trigger_auto/manual_rca, get_rca_result_view, get_rca_results. |
| `api/services/feedback_service.py` | Feedback logic: confirm, reject, reject-all, rollback with audit. |
| `api/utils/__init__.py` | Package init. |
| `api/utils/logging.py` | JobLogger for per-job log files. |

---

## agent/ — Log analysis agent (RAG, planning, tools)

| File | Description |
|------|-------------|
| `agent/README.md` | Agent architecture and usage. |
| `agent/schemas.py` | Shared schemas for agent. |
| `agent/tool_wrapper.py` | Wraps utilities as agent tools. |
| `agent/llm/__init__.py` | Package init. |
| `agent/llm/llama_client.py` | Llama API client. |
| `agent/llm/ollama_client.py` | Ollama API client for local LLM. |
| `agent/planner/__init__.py` | Package init. |
| `agent/planner/heuristic_planner.py` | Rule-based planning without LLM. |
| `agent/planner/llm_planner.py` | LLM-based planning. |
| `agent/planner/plan_models.py` | Plan step models. |
| `agent/planner/planner_router.py` | Routes to heuristic or LLM planner. |
| `agent/rag/__init__.py` | Package init. |
| `agent/rag/chunker.py` | Chunks logs for embedding. |
| `agent/rag/embedder.py` | Embedding generation (local or OpenAI). |
| `agent/rag/index_manager.py` | Manages vector index lifecycle. |
| `agent/rag/retriever.py` | Retrieves relevant chunks by similarity. |
| `agent/rag/vector_store.py` | ChromaDB vector store wrapper. |
| `agent/roles/__init__.py` | Package init. |
| `agent/roles/investigation_agent.py` | Investigation agent role. |
| `agent/roles/reporter_agent.py` | Reporter agent role. |
| `agent/roles/retrieval_agent.py` | Retrieval agent role. |
| `agent/runtime/__init__.py` | Package init. |
| `agent/runtime/job_models.py` | Job runtime models. |
| `agent/runtime/planner.py` | Runtime planner integration. |
| `agent/runtime/storage.py` | Artifact storage. |
| `agent/runtime/tool_executor.py` | Executes agent tools. |
| `agent/runtime/tool_registry.py` | Registers available tools. |
| `agent/runtime/worker.py` | Pipeline worker; runs plan steps. |

---

## artifacts/ — Evidence and job artifacts

| File | Description |
|------|-------------|
| `artifacts/__init__.py` | Package init. |
| `artifacts/evidence_store.py` | Evidence bundle storage (LocalFileEvidenceStore). |

---

## code_testing/ — Tests

| File | Description |
|------|-------------|
| `code_testing/README_API_TESTS.md` | API test documentation. |
| `code_testing/test_api.py` | API endpoint tests. |
| `code_testing/test_artifact_paths_contract.py` | Artifact path contract tests. |
| `code_testing/test_filter_log_level.py` | Filter log level tests. |
| `code_testing/test_index_reuse.py` | Index reuse tests. |
| `code_testing/test_job_status_enum.py` | Job status enum tests. |
| `code_testing/test_log_summary.py` | Log summary tests. |
| `code_testing/test_multi_agent_outputs.py` | Multi-agent output tests. |
| `code_testing/test_pipeline_smoke.py` | Pipeline smoke tests. |
| `code_testing/test_planner_retrieval.py` | Planner retrieval tests. |
| `code_testing/test_rag_chunker.py` | RAG chunker tests. |
| `code_testing/test_retrieve_context_smoke.py` | Retrieve context smoke tests. |
| `code_testing/test_schema_contract.py` | Schema contract tests. |
| `code_testing/test_search_on_keyword.py` | Keyword search tests. |
| `code_testing/test_stacktrace.py` | Stacktrace parsing tests. |
| `code_testing/test_time_slice.py` | Time slice tests. |
| `code_testing/test_worker_never_crashes.py` | Worker resilience tests. |

---

## docs/ — Documentation

| File | Description |
|------|-------------|
| `docs/README.md` | Docs index. |
| `docs/AUDIT_7_TASKS.md` | Audit task list. |
| `docs/ai_agent_implementation_roadmap.md` | Agent implementation roadmap. |
| `docs/architecture_overview.md` | System architecture overview. |
| `docs/desktop_app_tech_stack_recommendations.md` | Desktop app tech stack. |
| `docs/desktop_ui_workflow.md` | Desktop UI workflow. |
| `docs/error_code_workflow.md` | Error code handling. |
| `docs/filter_log_level_workflow.md` | Filter log level workflow. |
| `docs/job_execution_workflow.md` | Job execution flow. |
| `docs/mobile_ui_design.md` | Mobile UI design. |
| `docs/pipeline_flow_diagram.md` | Pipeline flow diagram. |
| `docs/quick_start_agent.md` | Quick start guide. |
| `docs/rag_design_proposal.md` | RAG design proposal. |
| `docs/rag_implementation_summary.md` | RAG implementation summary. |
| `docs/run_functions_api.md` | Run functions API. |
| `docs/time_slice_workflow.md` | Time slice workflow. |
| `docs/worker_runtime_guide.md` | Worker runtime guide. |

---

## evaluation/ — Evaluation

| File | Description |
|------|-------------|
| `evaluation/rca_metrics.md` | RCA evaluation metrics. |

---

## feedback/ — Feedback specs

| File | Description |
|------|-------------|
| `feedback/confirmation_workflow.md` | Confirmation workflow spec. |

---

## gates/ — Quality gates

| File | Description |
|------|-------------|
| `gates/__init__.py` | Package init. |
| `gates/post_ingestion_gate.py` | Validates anomaly structure after ingestion (I1, I2, I12). |
| `gates/pre_rca_gate.py` | Validates before RCA (accepted block, idempotency, structural). |

---

## graph/ — Neo4j knowledge graph

| File | Description |
|------|-------------|
| `graph/__init__.py` | Package init. |
| `graph/neo4j_client.py` | Neo4j client (execute_read, execute_write, execute_write_tx). |
| `graph/writer.py` | Graph writer: upsert nodes, link edges, RCA_ATTRIBUTED, feedback updates. |
| `graph/migrations.py` | Neo4j schema migrations (constraints, indexes). |
| `graph/ontology.md` | Ontology: nodes, file identity, canonical path. |
| `graph/relationships.md` | Relationship specs (HAS_FRAME, RCA_ATTRIBUTED, IN_FILE, etc.). |
| `graph/models.md` | Node model definitions. |
| `graph/constraints.md` | Constraint definitions. |
| `graph/invariants.md` | Graph invariants (I1–I16). |
| `graph/data_quality.md` | Data quality rules. |
| `graph/quality_gates.md` | Quality gate specs. |
| `graph/confidence_signals.md` | Confidence signal definitions. |
| `graph/evidence_bundle_contract.md` | Evidence bundle schema. |
| `graph/rca_run_lifecycle.md` | RCA run lifecycle, status transitions. |
| `graph/time_model.md` | Temporal model. |
| `graph/repo_drift_handling.md` | Repo drift handling. |

---

## ingestion/ — Ingestion specs

| File | Description |
|------|-------------|
| `ingestion/contracts.md` | Ingestion contracts. |
| `ingestion/deployment_spec.md` | Deployment ingestion spec. |
| `ingestion/failure_modes.md` | Failure mode handling. |
| `ingestion/git_mining_spec.md` | Git mining spec. |
| `ingestion/idempotency.md` | Idempotency rules. |
| `ingestion/ordering.md` | Ordering guarantees. |
| `ingestion/stacktrace_parsing_spec.md` | Stacktrace parsing spec. |

---

## jobs/ — Background jobs

| File | Description |
|------|-------------|
| `jobs/__init__.py` | Package init. |
| `jobs/job_locking.py` | Per-anomaly lock (Redis + in-memory fallback). |
| `jobs/rca_jobs.py` | Celery tasks: run_auto_rca_job, run_manual_rca_job. |

---

## legacy/ — Legacy API

| File | Description |
|------|-------------|
| `legacy/README.md` | Legacy API notes. |
| `legacy/legacy_api_app.py` | Legacy FastAPI app. |

---

## machine_learning/ — ML anomaly detection

| File | Description |
|------|-------------|
| `machine_learning/__init__.py` | Package init. |
| `machine_learning/config.py` | ML config. |
| `machine_learning/data/__init__.py` | Package init. |
| `machine_learning/data/hdfs_loader.py` | HDFS log loader. |
| `machine_learning/data/labels.py` | Label handling. |
| `machine_learning/data/parser.py` | Log parser. |
| `machine_learning/features/__init__.py` | Package init. |
| `machine_learning/features/embeddings.py` | Feature embeddings. |
| `machine_learning/features/templates.py` | Template extraction. |
| `machine_learning/features/vectorize.py` | Vectorization. |
| `machine_learning/models/__init__.py` | Package init. |
| `machine_learning/models/evaluator.py` | Model evaluator. |
| `machine_learning/models/isolation_forest.py` | Isolation Forest model. |
| `machine_learning/pipelines/__init__.py` | Package init. |
| `machine_learning/pipelines/infer_anomaly.py` | Inference pipeline. |
| `machine_learning/pipelines/train_anomaly.py` | Training pipeline. |

---

## rca_engine/ — RCA pipeline

| File | Description |
|------|-------------|
| `rca_engine/__init__.py` | Package init; exports run_deterministic_rca, etc. |
| `rca_engine/candidate_generator.py` | Generates candidate files from Anomaly→HAS_FRAME→StackFrame→IN_FILE→File. |
| `rca_engine/ranking_model.py` | Weighted scoring, weight redistribution, top-N ranking. |
| `rca_engine/rca_runner.py` | Orchestrates pre_rca_gate, candidates, signals, ranking, evidence, RCA_ATTRIBUTED. |
| `rca_engine/deterministic_rca_runner.py` | Thin wrapper delegating to rca_runner.run_deterministic_rca. |
| `rca_engine/signal_computation.py` | Computes 10 signals per candidate (Neo4j queries). |
| `rca_engine/deterministic_rca_v1.md` | Deterministic RCA v1 spec. |
| `rca_engine/evidence_bundle_mapping.md` | Evidence bundle field mapping. |
| `rca_engine/gate_integration.md` | Gate integration spec. |
| `rca_engine/orchestration_flow.md` | Orchestration flow. |
| `rca_engine/rerun_policy.md` | Rerun policy. |
| `rca_engine/auto_accept_policy_future.md` | Auto-accept policy (future). |
| `rca_engine/new_evidence_policy.md` | New evidence policy. |

---

## scripts/ — Scripts

| File | Description |
|------|-------------|
| `scripts/run_api_local.md` | How to run API locally. |
| `scripts/run_job.py` | Run a job from CLI. |
| `scripts/smoke_test_graph.py` | Smoke test: migrations, anomaly, RCA, RCA_ATTRIBUTED. |
| `scripts/smoke_test_rca_api.py` | Smoke test: RCA API flow, confirm, verify, rollback. |
| `scripts/verify_pipeline.py` | Pipeline verification script. |

---

## utilities/ — Log utilities (agent tools)

| File | Description |
|------|-------------|
| `utilities/error_code.py` | Error code extraction. |
| `utilities/error_lines.py` | Error line extraction. |
| `utilities/filter_log_level.py` | Filter logs by level. |
| `utilities/log_summary.py` | Log summarization. |
| `utilities/log_utility_main.py` | Main entry for log utilities. |
| `utilities/retrieve_context.py` | Retrieve context for RAG. |
| `utilities/search_on_keyword.py` | Keyword search. |
| `utilities/stacktrace.py` | Stacktrace parsing. |
| `utilities/time_slice.py` | Time slice extraction. |
| `utilities/tool_result.py` | Tool result formatting. |

---

## Runtime directories (generated)

| Directory | Description |
|-----------|-------------|
| `artifacts/<job_id>/` | Job artifacts (retrieval.json, findings.json, final_answer.md). |
| `output/jobs/<job_id>/` | Pipeline output per job. |
| `output/indexes/` | Vector indexes. |
| `runs/<job_id>/` | Job run metadata. |
