# Job Execution Workflow

## Overview

This document describes the complete end-to-end workflow of executing a log analysis job, from CLI command to final result.

## Execution Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CLI Entry: scripts/run_job.py                           │
│    Input: --file, --query, --mode                          │
│    Output: JobResult + formatted display                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Worker: agent/runtime/worker.py                        │
│    • Creates job_id + job_dir                              │
│    • Creates JobContext (artifacts_dir, inputs_dir)       │
│    • Copies input files → inputs/                          │
│    • Writes initial job.json                               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Planner: agent/runtime/planner.py                       │
│    • Analyzes query                                         │
│    • Keyword matching (heuristic) or LLM (llm mode)        │
│    • Returns: List[ToolCall]                               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Tool Executor Loop: agent/runtime/tool_executor.py      │
│    For each ToolCall:                                       │
│    • Maps file_path → job-scoped copy                      │
│    • Injects output_dir = ctx.artifacts_dir                │
│    • Calls tool function                                    │
│    • Validates: validate_tool_result()                     │
│    • Enforces: artifact paths under job_dir                │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Tool: utilities/*.py                                    │
│    • Reads: /job/path/inputs/<file>                        │
│    • Processes log content                                  │
│    • Writes: /job/path/artifacts/<output>                  │
│    • Returns: ToolResult dict                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. Worker: Collects Results                                │
│    • Persists: tool_results/<n>_<toolname>.json            │
│    • Extracts artifacts → ArtifactRef                       │
│    • Builds final_answer                                    │
│    • Creates JobResult                                      │
│    • Writes final job.json                                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. CLI: Displays Results                                   │
│    • Prints JobResult fields                               │
│    • Shows directory paths                                  │
│    • Exits with code 0/1                                   │
└─────────────────────────────────────────────────────────────┘
```

## Step-by-Step Workflow

### Phase 1: CLI Entry

**File**: `scripts/run_job.py`

1. Parse command-line arguments:
   - `--file`: Path to log file
   - `--query`: Natural language query
   - `--mode`: "heuristic" or "llm" (default: "heuristic")

2. Validate file exists

3. Create `JobRequest`:
   ```python
   JobRequest(
       query="Summarize errors",
       file_paths=["/absolute/path/to/data/sample.log"]
   )
   ```

4. Call `run_job(request, mode)`

### Phase 2: Job Initialization

**File**: `agent/runtime/worker.py`

1. **Start Timing**: `RunTiming(started_at=datetime.now())`

2. **Create Job Directory**: `create_job_dir()`
   - Generates UUID: `a6ac1524-0a5f-4f57-82a0-e4631342f58e`
   - Creates: `output/jobs/<job_id>/`

3. **Initialize Collections**: Empty lists for `tool_calls`, `tool_results`, `artifacts`, `warnings`, `errors`

4. **Create Job Context**: `create_job_context(job_id, job_dir)`
   - Creates: `artifacts/` and `inputs/` subdirectories
   - Returns `JobContext` with all paths

5. **Copy Input Files**: `copy_input_files(context, request.file_paths)`
   - Copies: `data/sample.log` → `output/jobs/<job_id>/inputs/sample.log`
   - Updates: `context.input_files` mapping

6. **Write Initial State**: `write_job_state(job_dir, initial_state)`
   - Writes: `job.json` with "running" status

### Phase 3: Planning

**File**: `agent/runtime/planner.py`

1. **Prepare Planning Request**: Use job-scoped file paths

2. **Call Planner**: `plan_steps(planning_request, mode="heuristic")`

3. **Heuristic Planning** (if mode="heuristic"):
   - Lowercase query: `"summarize errors"`
   - Keyword matching:
     - `"summary"` → `run_log_summary`
     - `"error"` + `"code"` → `run_error_code_search`
     - etc.
   - Creates `ToolCall` objects (without `output_dir`)

4. **LLM Planning** (if mode="llm"):
   - Prompts LLM with available tools
   - LLM returns JSON list of tool calls
   - Validates and creates `ToolCall` objects

5. **Returns**: `List[ToolCall]`

### Phase 4: Tool Execution Loop

**File**: `agent/runtime/worker.py` + `agent/runtime/tool_executor.py`

For each `ToolCall`:

1. **Mark Running**: Set `started_at` and `status="running"`

2. **Execute Tool**: `tool_executor.execute(tool_name, arguments, ctx=context)`

   **Inside ToolExecutor:**
   
   a. **Prepare Arguments**:
      - Map `file_path` → job-scoped copy (if in `ctx.input_files`)
      - Inject `output_dir = ctx.artifacts_dir` (always override)
   
   b. **Fetch Tool**: `get_tool(tool_name)` from registry
   
   c. **Call Tool**: `tool_func(**prepared_args)`
      - Tool reads from `inputs/` directory
      - Tool writes to `artifacts/` directory
      - Tool returns raw `ToolResult` dict
   
   d. **Validate**: `validate_tool_result(raw_result)`
      - Normalizes structure
      - Ensures required fields
   
   e. **Enforce Paths**: `_enforce_artifact_paths(validated_result, ctx)`
      - Validates all artifact paths under `job_dir`
      - Detects path escapes
      - Rewrites paths if needed

3. **Process Result**:
   - Append to `tool_results`
   - Persist to `tool_results/<n>_<toolname>.json`
   - Extract artifacts → `ArtifactRef`
   - Update `tool_call` metadata
   - Collect errors/warnings

4. **Handle Exceptions**: Convert to error `ToolResult` (never crash)

5. **Append Tool Call**: Add to `tool_calls` list

### Phase 5: Final Answer Generation

**File**: `agent/runtime/worker.py`

1. **Build Final Answer**: `_build_final_answer(request, tool_results, artifacts, mode)`

2. **Heuristic Mode**:
   - Extract summaries from successful tool results
   - List artifact paths
   - Combine into text

3. **LLM Mode** (if available):
   - Compose natural language answer from tool results
   - LLM narrates (doesn't compute)

### Phase 6: Job Finalization

**File**: `agent/runtime/worker.py`

1. **Calculate Timing**: `duration_ms = (finished_at - started_at).total_seconds() * 1000`

2. **Determine Status**: `"succeeded"` if no errors, else `"failed"`

3. **Create JobResult**: Pydantic model with all data

4. **Write Final State**: `write_job_state(job_dir, job_result.model_dump())`
   - Updates `job.json` with complete results

5. **Return**: `JobResult` to CLI

### Phase 7: CLI Output

**File**: `scripts/run_job.py`

1. **Display Results**:
   - Job ID and status
   - Directory paths (absolute)
   - Final answer
   - Generated artifacts
   - Errors and warnings
   - Duration

2. **Exit**: Code `0` (success) or `1` (failure)

## File System State

### Before Job Execution

```
output/
└── (empty or existing files)
```

### After Job Execution

```
output/jobs/<job_id>/
├── job.json                    # Complete job state
├── artifacts/                  # Tool outputs
│   └── sample_log_summary.txt
├── tool_results/               # Individual tool results
│   └── 000_run_log_summary.json
└── inputs/                     # Copied input files
    └── sample.log
```

## Data Flow

### Input Flow

```
CLI Arguments
    ↓
JobRequest (Pydantic)
    ↓
Worker.run_job()
    ↓
JobContext (with paths)
    ↓
Planner.plan_steps()
    ↓
List[ToolCall]
    ↓
ToolExecutor.execute()
    ↓
Tool Function (run_*)
```

### Output Flow

```
Tool Function
    ↓
Raw ToolResult dict
    ↓
validate_tool_result()
    ↓
Validated ToolResult dict
    ↓
_enforce_artifact_paths()
    ↓
ToolResult with enforced paths
    ↓
Worker collects results
    ↓
JobResult (Pydantic)
    ↓
job.json + CLI output
```

## Key Invariants

1. **Job-Scoped Paths**: All files under `output/jobs/<job_id>/`
2. **Validated Results**: All tool results pass schema validation
3. **No Crashes**: All exceptions converted to errors
4. **Path Enforcement**: Artifact paths validated and rewritten
5. **Persistence**: Tool results saved to `tool_results/` directory

## Error Scenarios

### Tool Failure

1. Tool raises exception
2. `ToolExecutor` catches exception
3. Returns error `ToolResult` with `status="error"`
4. Worker continues execution
5. Error added to `JobResult.errors`

### File Not Found

1. `copy_input_files()` raises `FileNotFoundError`
2. Worker catches exception
3. Adds error to `errors` list
4. Job continues (may fail later when tool tries to read)

### Path Escape

1. Tool returns artifact path outside job directory
2. `_enforce_artifact_paths()` detects escape
3. Converts to error in `ToolResult.errors`
4. Artifact excluded from validated artifacts
5. `ToolResult.status` set to `"error"`

## Performance Considerations

- **Sequential Execution**: Tools executed one at a time (future: parallel)
- **File Copying**: Input files copied upfront (ensures isolation)
- **Validation Overhead**: Each tool result validated (ensures correctness)
- **Path Enforcement**: All artifact paths checked (ensures security)

## Testing the Workflow

Run a test job:

```bash
python scripts/run_job.py --file data/sample.log --query "Summarize errors"
```

Verify:

1. Job directory created: `output/jobs/<job_id>/`
2. Input file copied: `inputs/sample.log` exists
3. Artifacts created: `artifacts/` contains tool outputs
4. Tool results persisted: `tool_results/` contains JSON files
5. Job state written: `job.json` contains complete state
6. No root output files: Nothing in `output/` except `jobs/`

## Troubleshooting

### Job Directory Not Created

- Check `create_job_dir()` permissions
- Verify `output/jobs/` directory exists

### Artifacts Not Under Job Directory

- Verify `ToolExecutor` injects `output_dir` from `JobContext`
- Check `_enforce_artifact_paths()` is called

### Tool Results Not Persisted

- Check `write_tool_result()` permissions
- Verify `tool_results/` directory created

### Job Crashes

- Check exception handling in `run_job()`
- Verify all exceptions caught and converted to errors
