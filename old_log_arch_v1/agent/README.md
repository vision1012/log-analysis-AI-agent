# Agent Module

This directory contains the AI agent implementation components.

## Structure

```
agent/
├── schemas.py              # Pydantic ToolResult schema definitions
├── tool_wrapper.py         # Tool result validator and normalizer
├── llm/                    # LLM client for OpenAI-compatible APIs
│   ├── __init__.py
│   └── llama_client.py     # LLaMA client with retry handling
└── runtime/                # Worker runtime system
    ├── __init__.py
    ├── job_models.py       # JobRequest, JobResult, JobContext models
    ├── worker.py           # Main worker: run_job()
    ├── planner.py          # Tool planning (heuristic + LLM)
    ├── tool_registry.py    # Tool name → function mapping
    ├── tool_executor.py    # Tool execution with validation
    └── storage.py          # Job directory and file management
```

## Core Components

- **`schemas.py`** - Pydantic schema definitions for ToolResult contract
- **`tool_wrapper.py`** - Tool result validator and normalizer
- **`llm/llama_client.py`** - LLaMA client for LLM integration
- **`runtime/worker.py`** - Main worker orchestrates job execution
- **`runtime/planner.py`** - Determines which tools to call
- **`runtime/tool_executor.py`** - Executes tools with validation
- **`runtime/tool_registry.py`** - Maps tool names to functions
- **`runtime/storage.py`** - Job directory and file management
- **`runtime/job_models.py`** - Pydantic models for job lifecycle

## Setup

1. Install dependencies:
   ```bash
   pip install "pydantic>=2.6"
   ```

2. The schema validation is ready to use:
   ```python
   from agent.tool_wrapper import validate_tool_result
   from utilities.log_summary import run_log_summary
   
   result = run_log_summary("file.log")
   validated = validate_tool_result(result)  # Guaranteed schema-compliant
   ```

## Schema Contract

All `run_*()` functions must return data that validates against `ToolResult` schema:

- `tool`: Tool name (string)
- `status`: "success" | "error"
- `input`: ToolInput (file_path + options)
- `summary`: ToolSummary (headline + key_metrics)
- `data`: ToolData (items + text + json)
- `artifacts`: List[ToolArtifact]
- `warnings`: List[ToolWarning]
- `errors`: List[ToolError]

The schema uses `extra="forbid"` to prevent schema drift.
