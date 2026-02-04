# Agent Module

This directory contains the AI agent implementation components.

## Files

- **`schemas.py`** - Pydantic schema definitions for ToolResult contract
- **`tool_wrapper.py`** - Tool result validator and normalizer
- **`agent_core.py`** - (Placeholder) Main agent orchestration
- **`tools.py`** - (Placeholder) Tool registry and executor
- **`reasoning.py`** - (Placeholder) Agent reasoning logic

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
