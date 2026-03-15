# Log Analysis AI Agent – File Structure

```
log-analysis-AI-agent/
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── requirements.txt
│
├── api/                          # FastAPI backend
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── EXAMPLE_CURL_COMMANDS.md
│   ├── core/
│   │   ├── __init__.py
│   │   └── paths.py
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── observability.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── jobs.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── job.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── job_store.py
│   │   └── runner.py
│   └── utils/
│       ├── __init__.py
│       └── logging.py
│
├── agent/                        # Log analysis agent (RAG, planning, tools)
│   ├── README.md
│   ├── schemas.py
│   ├── tool_wrapper.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── llama_client.py
│   │   └── ollama_client.py
│   ├── planner/
│   │   ├── __init__.py
│   │   ├── heuristic_planner.py
│   │   ├── llm_planner.py
│   │   ├── plan_models.py
│   │   └── planner_router.py
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── index_manager.py
│   │   ├── retriever.py
│   │   └── vector_store.py
│   ├── roles/
│   │   ├── __init__.py
│   │   ├── investigation_agent.py
│   │   ├── reporter_agent.py
│   │   └── retrieval_agent.py
│   └── runtime/
│       ├── __init__.py
│       ├── job_models.py
│       ├── planner.py
│       ├── storage.py
│       ├── tool_executor.py
│       ├── tool_registry.py
│       └── worker.py
│
├── code_testing/                 # Tests
│   ├── README_API_TESTS.md
│   ├── test_api.py
│   ├── test_artifact_paths_contract.py
│   ├── test_filter_log_level.py
│   ├── test_index_reuse.py
│   ├── test_job_status_enum.py
│   ├── test_log_summary.py
│   ├── test_multi_agent_outputs.py
│   ├── test_pipeline_smoke.py
│   ├── test_planner_retrieval.py
│   ├── test_rag_chunker.py
│   ├── test_retrieve_context_smoke.py
│   ├── test_schema_contract.py
│   ├── test_search_on_keyword.py
│   ├── test_stacktrace.py
│   ├── test_time_slice.py
│   └── test_worker_never_crashes.py
│
├── docs/                         # Documentation
│   ├── README.md
│   ├── ai_agent_implementation_roadmap.md
│   ├── architecture_overview.md
│   ├── desktop_app_tech_stack_recommendations.md
│   ├── desktop_ui_workflow.md
│   ├── error_code_workflow.md
│   ├── filter_log_level_workflow.md
│   ├── job_execution_workflow.md
│   ├── mobile_ui_design.md
│   ├── mobile_ui_mockups.html
│   ├── pipeline_flow_diagram.md
│   ├── quick_start_agent.md
│   ├── rag_design_proposal.md
│   ├── rag_implementation_summary.md
│   ├── run_functions_api.md
│   ├── time_slice_workflow.md
│   ├── worker_runtime_guide.md
│   └── Log-Agent-RAG.png
│
├── legacy/                       # Legacy API
│   ├── README.md
│   └── legacy_api_app.py
│
├── scripts/                      # Run & test scripts
│   ├── poll_job.sh
│   ├── run_api_local.md
│   ├── run_job.py
│   ├── setup_and_test_api.sh
│   ├── smoke_mode.sh
│   ├── smoke_status.sh
│   ├── test_api_local.sh
│   ├── test_endpoints.sh
│   └── verify_pipeline.py
│
├── utilities/                    # Log utilities (tools used by agent)
│   ├── error_code.py
│   ├── error_lines.py
│   ├── filter_log_level.py
│   ├── log_summary.py
│   ├── log_utility_main.py
│   ├── retrieve_context.py
│   ├── search_on_keyword.py
│   ├── stacktrace.py
│   ├── time_slice.py
│   └── tool_result.py
│
├── output/                      # Generated (indexes, vector DB; often gitignored)
│   └── ...
│
└── runs/                        # Job run data (runs/<job_id>/job.json; often gitignored)
    └── ...
```

## Summary

| Directory    | Purpose |
|-------------|---------|
| **api/**    | FastAPI app: config, routers (jobs, health), schemas, job store, runner, paths, logging. |
| **agent/**  | Agent logic: LLM clients, planner (heuristic/LLM), RAG (chunker, embedder, retriever), roles (retrieval, investigation, reporter), runtime (worker, tool executor, storage). |
| **code_testing/** | Tests for API, pipeline, RAG, utilities, schema. |
| **docs/**    | All markdown/docs: architecture, workflows, desktop/mobile UI, pipeline diagram, tech stack. |
| **legacy/**  | Old API app. |
| **scripts/** | Shell/Python scripts: run job, poll job, smoke tests, API setup. |
| **utilities/** | Log tools: error_code, filter_log_level, log_summary, stacktrace, time_slice, etc. |
| **output/**  | Generated output (e.g. indexes); may be gitignored. |
| **runs/**    | Per-job run data; may be gitignored. |
