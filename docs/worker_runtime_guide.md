# Worker Runtime System Guide

## Overview

The Worker Runtime System (`agent/runtime/`) is the core execution engine for log analysis jobs. It orchestrates tool execution, manages job lifecycle, and enforces Step 6 rules for job-scoped paths and artifact management.

## Architecture

```
agent/runtime/
├── job_models.py      # Pydantic models: JobRequest, JobResult, JobContext, ToolCall
├── worker.py          # Main worker: run_job() orchestrates entire job lifecycle
├── planner.py         # Planning logic: heuristic and LLM-based tool selection
├── tool_registry.py   # Tool registry: maps tool names to run_*() functions
├── tool_executor.py   # Tool executor: executes tools with validation and path enforcement
└── storage.py         # Storage helpers: job directories, file copying, state persistence
```

## Core Components

### 1. Job Models (`job_models.py`)

Pydantic models that define the job lifecycle:

- **`JobRequest`**: Input to worker
  - `query`: Natural language query
  - `file_paths`: List of log files to analyze
  - `options`: JobOptions (timeout, max_tool_calls, etc.)

- **`JobResult`**: Output from worker
  - `job_id`: Unique identifier
  - `status`: "succeeded" | "failed"
  - `final_answer`: Natural language answer
  - `tool_calls`: List of ToolCall metadata
  - `tool_results`: List of validated ToolResult dicts
  - `artifacts`: List of ArtifactRef
  - `warnings`, `errors`: Lists of strings
  - `timing`: RunTiming information

- **`JobContext`**: Runtime context for job execution
  - `job_id`: Unique identifier
  - `job_dir`: Path to job directory
  - `artifacts_dir`: Path to artifacts subdirectory
  - `inputs_dir`: Path to inputs subdirectory
  - `input_files`: Mapping from original to copied paths

- **`ToolCall`**: Metadata about a tool invocation
  - `name`: Tool name (e.g., "run_log_summary")
  - `status`: "pending" | "running" | "success" | "error"
  - `arguments`: Dict of arguments passed to tool
  - `started_at`, `finished_at`: Timestamps
  - `summary`: Human-readable summary

### 2. Worker (`worker.py`)

Main entry point: `run_job(request: JobRequest, mode: str) -> JobResult`

**Execution Flow:**
1. Create job directory and context
2. Copy input files to `inputs/`
3. Write initial `job.json` state
4. Plan tool calls (heuristic or LLM)
5. Execute each tool via `ToolExecutor`
6. Persist tool results to `tool_results/`
7. Build final answer
8. Write final `job.json` state
9. Return `JobResult`

**Key Features:**
- Never crashes: All exceptions converted to `JobResult.errors`
- Job-scoped paths: All files under `output/jobs/<job_id>/`
- Tool result persistence: Each tool result saved as JSON
- Artifact aggregation: Collects all artifacts from tools

### 3. Planner (`planner.py`)

Determines which tools to call: `plan_steps(request: JobRequest, mode: str) -> List[ToolCall]`

**Modes:**
- **Heuristic**: Keyword-based tool selection
  - "summary" → `run_log_summary`
  - "error" + "code" → `run_error_code_search` or `run_error_code_extract_all`
  - "stacktrace" → `run_stacktrace`
  - "time" + "range" → `run_time_slice`
  - etc.

- **LLM**: Uses LLaMA to select tools based on query
  - Prompts LLM with available tools
  - LLM returns JSON list of tool calls
  - Validates and returns `ToolCall` objects

**Important**: LLM only selects tools and arguments. All computation is done by tools.

### 4. Tool Registry (`tool_registry.py`)

Maps tool names to functions:

```python
TOOL_REGISTRY = {
    "run_log_summary": run_log_summary,
    "run_time_slice": run_time_slice,
    "run_search_keyword": run_search_keyword,
    # ... etc
}
```

**Functions:**
- `list_tools() -> Dict[str, Callable]`: Get all registered tools
- `get_tool(name: str) -> Callable`: Get specific tool function

### 5. Tool Executor (`tool_executor.py`)

Executes tools with validation and path enforcement: `execute(tool_name: str, args: dict, ctx: JobContext) -> dict`

**Steps:**
1. Map `file_path` to job-scoped copy (if in `ctx.input_files`)
2. Inject `output_dir = ctx.artifacts_dir` (always override)
3. Fetch tool function from registry
4. Call tool safely
5. Validate output with `validate_tool_result()`
6. Enforce artifact paths (must be under job directory)
7. Return validated `ToolResult` dict

**Path Enforcement:**
- All artifact paths validated against `ctx.job_dir`
- Path escapes detected and converted to errors
- Paths rewritten to be relative to `artifacts_dir`

### 6. Storage (`storage.py`)

Helpers for job directory and file management:

- **`create_job_dir()`**: Creates `output/jobs/<uuid>/`
- **`create_job_context()`**: Creates `artifacts/` and `inputs/` subdirectories
- **`copy_input_files()`**: Copies input files to `inputs/` and updates context mapping
- **`write_job_state()`**: Writes `job.json` with job state
- **`write_tool_result()`**: Writes individual tool result JSON files
- **`artifact_ref_from_path()`**: Creates `ArtifactRef` from file path

## Job Directory Structure

```
output/jobs/<job_id>/
├── job.json                    # Authoritative snapshot (initial + final state)
├── artifacts/                  # All tool-generated files
│   └── <tool_output_files>
├── tool_results/               # Individual tool result JSON files
│   ├── 000_run_log_summary.json
│   ├── 001_run_stacktrace.json
│   └── ...
└── inputs/                     # Copied input files
    └── <original_log_file>
```

## Usage Examples

### Basic Job Execution

```python
from agent.runtime.worker import run_job
from agent.runtime.job_models import JobRequest

request = JobRequest(
    query="Summarize errors",
    file_paths=["data/sample.log"]
)

result = run_job(request, mode="heuristic")

print(f"Job ID: {result.job_id}")
print(f"Status: {result.status}")
print(f"Final Answer: {result.final_answer}")
print(f"Tool Results: {len(result.tool_results)}")
print(f"Artifacts: {len(result.artifacts)}")
```

### Using JobContext Directly

```python
from agent.runtime.storage import create_job_context, copy_input_files
from agent.runtime.job_models import JobContext

job_id, job_dir = create_job_dir()
context = create_job_context(job_id, job_dir)
context = copy_input_files(context, ["data/sample.log"])

# Use context.artifacts_dir for tool output_dir
# Use context.input_files mapping for file_path
```

### Custom Tool Execution

```python
from agent.runtime.tool_executor import ToolExecutor
from agent.runtime.job_models import JobContext

executor = ToolExecutor()
context = create_job_context(job_id, job_dir)

result = executor.execute(
    "run_log_summary",
    {"file_path": "data/sample.log"},
    ctx=context
)

# Result is validated ToolResult dict
# Artifact paths enforced under job directory
```

## Step 6 Rules Enforcement

The runtime enforces Step 6 "long-term rules":

1. **Job-Scoped Paths**: All files under `output/jobs/<job_id>/`
2. **Input File Copying**: Original files copied to `inputs/`
3. **Artifact Path Validation**: All artifacts validated and rewritten if needed
4. **No Root Output Writes**: Tools cannot write to root `output/`
5. **Tool Result Persistence**: Each tool result saved to `tool_results/`
6. **No Crash Guarantee**: All exceptions converted to errors

## Error Handling

- **Tool Failures**: Converted to `status="error"` ToolResult dicts
- **Job Failures**: `JobResult.status = "failed"` with errors populated
- **Path Escapes**: Detected and converted to errors
- **File IO Errors**: Caught and added as warnings (never crash)

## Testing

Comprehensive test coverage:

- `test_artifact_paths_contract.py`: Verifies Step 6 path rules
- `test_worker_never_crashes.py`: Ensures worker resilience
- `test_schema_contract.py`: Validates ToolResult schema compliance

## Integration Points

### With Utilities Layer

- Tools registered in `tool_registry.py`
- All `run_*()` functions return `ToolResult` dicts
- Tools accept `output_dir` parameter (injected by executor)

### With LLM Layer

- `LLaMAClient` used for LLM planning mode
- LLM prompts restricted to tool selection (no computation)
- LLM used for final answer composition (optional)

### With Storage Layer

- Job directories created via `storage.py` helpers
- File copying handled by `copy_input_files()`
- State persistence via `write_job_state()`

## Best Practices

1. **Always use JobContext**: Ensures job-scoped paths
2. **Let ToolExecutor inject output_dir**: Don't hardcode paths
3. **Handle errors gracefully**: Check `status` and `errors` fields
4. **Use validated results**: All tool results pass schema validation
5. **Check artifacts**: Verify artifact paths are under job directory

## Future Enhancements

- Parallel tool execution
- Tool result caching
- Job result streaming
- Advanced retry logic
- Job queue integration
