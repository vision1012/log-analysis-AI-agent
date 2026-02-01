# Run Functions API Reference

## Overview

All `run_*()` functions are designed for AI agent integration. They:
- Accept all parameters as function arguments (no `input()`)
- Return structured dictionaries (no `print()` in core logic)
- Support configurable output directories
- Provide consistent error handling

## Common Return Structure

All `run_*()` functions return a dictionary with:

```python
{
    "success": bool,           # True if operation succeeded
    "error": str | None,       # Error message if success=False
    "output_file": str | None, # Path to output file (if write_file=True)
    # ... function-specific fields
}
```

## Function Reference

### 1. run_time_slice()

Slice log file by time range.

**Signature**:
```python
def run_time_slice(
    file_path: str,
    start_time: datetime,
    end_time: datetime,
    output_dir: str = "output",
    write_file: bool = True
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `start_time`: Start datetime for time range
- `end_time`: End datetime for time range
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output file (default: True)

**Returns**:
```python
{
    "success": bool,
    "lines_found": int,
    "output_file": str | None,
    "sample_lines": List[str],  # First 10 lines
    "time_range": {
        "start": str,  # ISO format
        "end": str     # ISO format
    },
    "error": str | None
}
```

**Example**:
```python
from datetime import datetime
result = run_time_slice(
    "logs/app.log",
    datetime(2024, 1, 1, 10, 0, 0),
    datetime(2024, 1, 1, 11, 0, 0)
)
```

---

### 2. run_search_keyword()

Search log file by keyword(s).

**Signature**:
```python
def run_search_keyword(
    file_path: str,
    keywords: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True,
    case_sensitive: bool = False
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `keywords`: Single keyword or list of keywords
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output file (default: True)
- `case_sensitive`: Case-sensitive search (default: False)

**Returns**:
```python
{
    "success": bool,
    "matched_lines": List[str],
    "output_file": str | None,
    "keywords": List[str],
    "match_count": int,
    "error": str | None
}
```

**Example**:
```python
result = run_search_keyword(
    "logs/app.log",
    ["error", "timeout"],
    case_sensitive=False
)
```

---

### 3. run_filter_log_level()

Filter log file by log level(s).

**Signature**:
```python
def run_filter_log_level(
    file_path: str,
    log_levels: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `log_levels`: Single level or list of levels (ERROR, FATAL, WARN, INFO, etc.)
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output files (default: True)

**Returns**:
```python
{
    "success": bool,
    "filtered_lines": List[str],  # All filtered lines combined
    "output_files": List[str],    # One file per level
    "counts_by_level": Dict[str, int],
    "error": str | None
}
```

**Example**:
```python
result = run_filter_log_level(
    "logs/app.log",
    ["ERROR", "FATAL"]
)
```

---

### 4. run_log_summary()

Generate comprehensive log summary.

**Signature**:
```python
def run_log_summary(
    file_path: str,
    output_dir: str = "output",
    write_file: bool = True
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write summary file (default: True)

**Returns**:
```python
{
    "success": bool,
    "summary": LogSummary,  # Dataclass with all summary data
    "output_file": str | None,
    "formatted_summary": str,  # Human-readable formatted text
    "error": str | None
}
```

**Example**:
```python
result = run_log_summary("logs/app.log")
if result["success"]:
    print(result["formatted_summary"])
```

---

### 5. run_stacktrace()

Extract and analyze stacktraces from log file.

**Signature**:
```python
def run_stacktrace(
    file_path: str,
    output_dir: str = "output",
    write_file: bool = True,
    include_context_lines: int = 4,
    min_stack_depth: int = 1,
    deduplicate: bool = False
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output files (default: True)
- `include_context_lines`: Context lines before stacktrace (default: 4)
- `min_stack_depth`: Minimum stack depth to include (default: 1)
- `deduplicate`: Whether to deduplicate stacktraces (default: False)

**Returns**:
```python
{
    "success": bool,
    "stacktraces": List[Stacktrace],
    "summary": StacktraceSummary,
    "output_files": {
        "clean_log": str | None,      # Log without stacktraces
        "stacktraces": str | None,    # Stacktraces only
        "summary": str | None         # Summary file
    },
    "formatted_summary": str,
    "error": str | None
}
```

**Example**:
```python
result = run_stacktrace(
    "logs/app.log",
    include_context_lines=2,
    deduplicate=True
)
```

---

### 6. run_error_code_search()

Search log file by error code(s).

**Signature**:
```python
def run_error_code_search(
    file_path: str,
    error_codes: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True,
    case_sensitive: bool = False
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `error_codes`: Single code or list of codes
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output file (default: True)
- `case_sensitive`: Case-sensitive search (default: False)

**Returns**:
```python
{
    "success": bool,
    "matched_lines": List[str],
    "output_file": str | None,
    "codes_found": List[str],
    "counts_by_code": Dict[str, int],
    "error": str | None
}
```

**Example**:
```python
result = run_error_code_search(
    "logs/app.log",
    ["ERR001", "ERR002"]
)
```

---

### 7. run_error_code_extract_all()

Extract all error codes from log file.

**Signature**:
```python
def run_error_code_extract_all(
    file_path: str,
    output_dir: str = "output",
    write_summary: bool = True
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `output_dir`: Output directory (default: "output")
- `write_summary`: Whether to write summary file (default: True)

**Returns**:
```python
{
    "success": bool,
    "matches": List[ErrorCodeMatch],
    "summary": ErrorCodeSummary,
    "summary_file": str | None,
    "formatted_summary": str,
    "error": str | None
}
```

**Example**:
```python
result = run_error_code_extract_all("logs/app.log")
```

---

### 8. run_error_lines()

Extract error lines from log file.

**Signature**:
```python
def run_error_lines(
    file_path: str,
    output_dir: str = "output",
    write_file: bool = True
) -> Dict
```

**Parameters**:
- `file_path`: Path to log file
- `output_dir`: Output directory (default: "output")
- `write_file`: Whether to write output file (default: True)

**Returns**:
```python
{
    "success": bool,
    "error_lines": List[str],
    "output_file": str | None,
    "error_count": int,
    "error": str | None
}
```

**Example**:
```python
result = run_error_lines("logs/app.log")
```

## Error Handling Pattern

All functions follow this pattern:

```python
if not os.path.isfile(file_path):
    return {
        "success": False,
        "error": f"File not found: {file_path}",
        # ... other fields with None/empty values
    }

try:
    # Process file
    result = process()
    return {
        "success": True,
        "error": None,
        # ... result data
    }
except Exception as e:
    return {
        "success": False,
        "error": str(e),
        # ... other fields with None/empty values
    }
```

## Usage Best Practices

1. **Always check `success` field**:
   ```python
   result = run_time_slice(...)
   if not result["success"]:
       print(f"Error: {result['error']}")
       return
   ```

2. **Use `write_file=False` for in-memory processing**:
   ```python
   result = run_search_keyword(file, "error", write_file=False)
   # Process result["matched_lines"] without creating file
   ```

3. **Custom output directories**:
   ```python
   result = run_log_summary(file, output_dir="custom/output")
   ```

4. **Chain operations**:
   ```python
   # First, filter by time
   time_result = run_time_slice(file, start, end, write_file=False)
   if time_result["success"]:
       # Then search in filtered lines
       search_result = run_search_keyword(
           file, "error", write_file=True
       )
   ```
