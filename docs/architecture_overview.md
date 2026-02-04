# Log Analysis AI Agent - Architecture Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE LAYER                                │
│                    (CLI / Interactive / API / AI Agent)                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
        ┌───────────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
        │   CLI Interface  │ │  AI Agent   │ │  REST API  │
        │ log_utility_main │ │  (Future)   │ │  (Future)  │
        └───────────┬──────┘ └──────┬──────┘ └─────┬──────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CORE FUNCTION LAYER                                │
│                    run_*() Functions (AI Agent Ready)                       │
│                    - No input() / print() in core logic                    │
│                    - Returns structured dictionaries                       │
│                    - Configurable output_dir                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐ ┌────────────────▼────────┐ ┌───────────────▼──────────┐
│ run_time_slice│ │ run_search_keyword      │ │ run_filter_log_level     │
│ run_log_summary│ │ run_error_code_search   │ │ run_stacktrace           │
│ run_error_lines│ │ run_error_code_extract  │ │                          │
└───────┬────────┘ └────────────────┬────────┘ └───────────────┬──────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      UTILITY FUNCTION LAYER                                │
│              Core Processing Functions (Reusable)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐ ┌────────────────▼────────┐ ┌───────────────▼──────────┐
│ slice_by_time │ │ search_keyword            │ │ filter_by_log_level      │
│ _extract_ts   │ │ extract_all_error_codes    │ │ extract_stacktraces      │
│               │ │ get_error_lines           │ │ summarize_log            │
└───────────────┘ └──────────────────────────┘ └──────────────────────────┘
```

## Three-Layer Architecture

### Layer 1: User Interface Layer
**Purpose**: Handle user interaction and input collection

- **CLI Interface** (`log_utility_main.py`)
  - Menu-driven interface
  - Uses `input()` for user prompts
  - Calls `run_*()` functions
  - Displays results from dictionaries

- **Interactive Functions** (e.g., `interactive_slice_by_time()`)
  - Can use `input()` for prompts
  - Wrapper around `run_*()` functions
  - For CLI convenience

- **Future**: AI Agent / REST API
  - Will call `run_*()` functions directly
  - No user interaction needed

### Layer 2: Core Function Layer (`run_*()`)
**Purpose**: AI Agent-ready functions with structured returns

**Characteristics**:
- ✅ No `input()` - all parameters passed as arguments
- ✅ No `print()` in core logic - returns structured data
- ✅ Returns dictionaries with consistent structure
- ✅ Configurable `output_dir` (default: "output")
- ✅ Optional file writing (`write_file` parameter)
- ✅ Error handling with error messages in return dict

**Available Functions**:
1. `run_time_slice()` - Slice logs by time range
2. `run_search_keyword()` - Search by keyword(s)
3. `run_filter_log_level()` - Filter by log level(s)
4. `run_log_summary()` - Generate log summary
5. `run_stacktrace()` - Extract stacktraces
6. `run_error_code_search()` - Search by error code(s)
7. `run_error_code_extract_all()` - Extract all error codes
8. `run_error_lines()` - Extract error lines

**Return Structure**:
```python
{
    "success": bool,
    "error": str | None,
    # Function-specific data fields
    "output_file": str | None,  # or "output_files": List[str]
    # ... other fields
}
```

### Layer 3: Utility Function Layer
**Purpose**: Core processing logic (reusable)

- Low-level functions that do the actual work
- Can be called by `run_*()` functions or directly
- Examples: `slice_by_time()`, `filter_by_log_level()`, `extract_stacktraces()`

## Data Flow

```
User/AI Agent
    │
    ▼
[Input Collection] (CLI/Interactive layer)
    │
    ▼
[run_*() Function] (Core layer)
    │
    ├─► Validate inputs
    ├─► Call utility functions
    ├─► Process results
    ├─► Format output
    └─► Return dictionary
    │
    ▼
[Dictionary Response]
    │
    ├─► success: bool
    ├─► error: str | None
    ├─► output_file: str | None
    └─► function-specific data
    │
    ▼
[Display/Use Results] (CLI/Agent layer)
```

## Function Categories

### 1. Time-based Operations
- `run_time_slice()` - Filter logs by time range

### 2. Search Operations
- `run_search_keyword()` - Search by keyword(s)
- `run_error_code_search()` - Search by error code(s)
- `run_error_code_extract_all()` - Extract all error codes

### 3. Filter Operations
- `run_filter_log_level()` - Filter by log level(s)
- `run_error_lines()` - Extract error lines

### 4. Analysis Operations
- `run_log_summary()` - Generate comprehensive summary
- `run_stacktrace()` - Extract and analyze stacktraces

## Integration Points

### For AI Agents
```python
# Direct function calls - no user interaction
result = run_time_slice(
    file_path="logs/app.log",
    start_time=datetime(2024, 1, 1, 10, 0, 0),
    end_time=datetime(2024, 1, 1, 11, 0, 0),
    output_dir="output",
    write_file=True
)

if result["success"]:
    print(f"Found {result['lines_found']} lines")
    # Use result["output_file"], result["sample_lines"], etc.
else:
    print(f"Error: {result['error']}")
```

### For CLI Users
```python
# Via log_utility_main.py menu
# User selects option, provides input
# CLI calls run_*() function
# CLI displays results from dictionary
```

## Output Directory Structure

```
project_root/
├── utilities/
│   ├── time_slice.py
│   ├── search_on_keyword.py
│   ├── filter_log_level.py
│   ├── log_summary.py
│   ├── stacktrace.py
│   ├── error_code.py
│   ├── error_lines.py
│   └── log_utility_main.py
├── output/                    # Default output directory
│   ├── sample_time_*.log
│   ├── keyword_*.log
│   ├── sample_ERROR.log
│   ├── sample_log_summary.txt
│   └── ...
└── code_testing/
    └── test_*.py
```

## Error Handling

All `run_*()` functions follow consistent error handling:

```python
try:
    # Validate inputs
    if not os.path.isfile(file_path):
        return {
            "success": False,
            "error": f"File not found: {file_path}",
            # ... other fields with None/empty values
        }
    
    # Process
    result = process_file(file_path)
    
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

## Testing

- **303 total tests** across 5 test files
- **34 new tests** for `run_*()` functions
- All tests passing ✅
- Comprehensive coverage of:
  - Success cases
  - Error handling
  - Edge cases
  - Dictionary structure validation

## Future Enhancements

1. **AI Agent Integration**
   - Function calling/tool definitions
   - Structured output schemas
   - Batch processing support

2. **REST API Layer**
   - FastAPI/Flask endpoints
   - JSON request/response
   - Async processing

3. **Additional Utilities**
   - Log correlation
   - Pattern detection
   - Anomaly detection
