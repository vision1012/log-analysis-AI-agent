# Log Analysis AI Agent - Architecture Diagram

## Complete System Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           EXTERNAL INTERFACES                                │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│  CLI Users     │         │   AI Agents     │        │   REST API        │
│  (Human)       │         │  (Programmatic) │        │  (Future)         │
└───────┬────────┘         └────────┬────────┘        └─────────┬─────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        INTERFACE LAYER                                       │
│  log_utility_main.py (CLI) | Interactive Functions | Direct API Calls       │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│ Menu Handler   │         │ Direct Call     │        │ API Endpoint      │
│ Uses input()   │         │ No input()      │        │ JSON Request      │
│ Calls run_*()  │         │ Calls run_*()   │        │ Calls run_*()    │
└───────┬────────┘         └────────┬────────┘        └─────────┬─────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                      CORE FUNCTION LAYER (run_*())                          │
│  AI Agent Ready - Structured Returns - No User Interaction                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│ Time Ops       │         │ Search Ops      │        │ Filter Ops        │
│ run_time_slice │         │ run_search_     │        │ run_filter_      │
│                │         │   keyword       │        │   log_level       │
│                │         │ run_error_code_ │        │ run_error_lines   │
│                │         │   search        │        │                   │
└───────┬────────┘         └────────┬────────┘        └─────────┬─────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│ Analysis Ops   │         │ Error Code Ops │        │                   │
│ run_log_summary│         │ run_error_code_│        │                   │
│ run_stacktrace │         │   extract_all  │        │                   │
└───────┬────────┘         └────────┬────────┘        └───────────────────┘
        │                           │
        └───────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    UTILITY FUNCTION LAYER                                    │
│  Core Processing Logic (Reusable Functions)                                 │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│ Time Utils     │         │ Search Utils    │        │ Filter Utils      │
│ slice_by_time │         │ search_keyword  │        │ filter_by_        │
│ _extract_ts   │         │ extract_all_    │        │   log_level       │
│               │         │   error_codes   │        │ get_error_lines   │
└───────┬────────┘         └────────┬────────┘        └─────────┬─────────┘
        │                           │                           │
        └───────────────────────────┼───────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐         ┌────────▼────────┐        ┌─────────▼─────────┐
│ Analysis Utils│         │ Stacktrace Utils│        │                   │
│ summarize_log │         │ extract_       │        │                   │
│ format_summary│         │   stacktraces  │        │                   │
└───────┬────────┘         └────────┬────────┘        └───────────────────┘
        │                           │
        └───────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            OUTPUT LAYER                                      │
│  output/ directory | Dictionary Returns | File System                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow Diagram

```
┌──────────────┐
│ User/Agent   │
│   Input      │
└──────┬───────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Input Collection                   │
│  - CLI: input() prompts            │
│  - Agent: Function parameters      │
│  - API: JSON request body          │
└──────┬──────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  run_*() Function Call              │
│  - Validate inputs                  │
│  - Process file                     │
│  - Generate results                 │
│  - Format output                    │
└──────┬──────────────────────────────┘
       │
       ├─────────────────┐
       │                 │
       ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ Dictionary   │  │ Output File  │
│ Return       │  │ (optional)   │
│              │  │              │
│ {            │  │ output/      │
│   success:   │  │   file.log   │
│   true,      │  │              │
│   data: ...  │  │              │
│ }            │  │              │
└──────┬───────┘  └──────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Result Display/Use                 │
│  - CLI: print() results              │
│  - Agent: Process dictionary         │
│  - API: JSON response                │
└─────────────────────────────────────┘
```

## Function Call Hierarchy

```
User/AI Agent
    │
    ├─► CLI Menu (log_utility_main.py)
    │   │
    │   └─► run_*() functions
    │       │
    │       └─► Utility functions
    │
    ├─► Direct Function Call
    │   │
    │   └─► run_*() functions
    │       │
    │       └─► Utility functions
    │
    └─► Interactive Functions
        │
        └─► run_*() functions
            │
            └─► Utility functions
```

## File Organization

```
utilities/
├── time_slice.py
│   ├── slice_by_time()              # Utility
│   ├── _extract_timestamp()         # Helper
│   ├── slice_by_time_to_file()     # Wrapper
│   ├── interactive_slice_by_time() # Interactive
│   └── run_time_slice()             # Core (AI-ready)
│
├── search_on_keyword.py
│   ├── search_keyword()             # Utility
│   └── run_search_keyword()         # Core (AI-ready)
│
├── filter_log_level.py
│   ├── filter_by_log_level()        # Utility
│   ├── _extract_log_level()         # Helper
│   ├── filter_by_log_level_to_file() # Wrapper
│   ├── interactive_filter_by_log_level() # Interactive
│   └── run_filter_log_level()       # Core (AI-ready)
│
├── log_summary.py
│   ├── summarize_log()              # Utility
│   ├── format_summary()             # Formatter
│   ├── summarize_log_to_file()     # Wrapper
│   └── run_log_summary()            # Core (AI-ready)
│
├── stacktrace.py
│   ├── extract_stacktraces()        # Utility
│   ├── extract_stacktraces_to_files() # Wrapper
│   └── run_stacktrace()             # Core (AI-ready)
│
├── error_code.py
│   ├── search_by_error_code()       # Utility
│   ├── extract_all_error_codes()    # Utility
│   ├── search_by_error_code_to_file() # Wrapper
│   ├── interactive_search_by_error_code() # Interactive
│   ├── run_error_code_search()      # Core (AI-ready)
│   └── run_error_code_extract_all() # Core (AI-ready)
│
├── error_lines.py
│   ├── get_error_lines()            # Utility
│   └── run_error_lines()            # Core (AI-ready)
│
└── log_utility_main.py
    └── main()                        # CLI Interface
        └── Calls run_*() functions
```

## Return Dictionary Structure

All `run_*()` functions return dictionaries with this structure:

```
{
    "success": bool              ──┐
    "error": str | None          ──┤ Common fields
    "output_file": str | None    ──┘
    
    ┌─ Function-specific fields ─┐
    │                             │
    │ For run_time_slice():       │
    │   "lines_found": int        │
    │   "sample_lines": List[str] │
    │   "time_range": dict        │
    │                             │
    │ For run_search_keyword():   │
    │   "matched_lines": List[str]│
    │   "keywords": List[str]     │
    │   "match_count": int        │
    │                             │
    │ For run_filter_log_level(): │
    │   "filtered_lines": List[str]│
    │   "output_files": List[str] │
    │   "counts_by_level": dict   │
    │                             │
    │ ... and so on               │
    └─────────────────────────────┘
}
```

## Integration Examples

### Example 1: CLI Usage
```
User → Menu → Choice "1" → Input file/keyword → run_search_keyword() → Display results
```

### Example 2: AI Agent Usage
```python
# Agent directly calls run_*() function
result = run_time_slice(
    file_path="logs/app.log",
    start_time=datetime(2024, 1, 1, 10, 0, 0),
    end_time=datetime(2024, 1, 1, 11, 0, 0)
)

# Agent processes dictionary response
if result["success"]:
    analyze(result["sample_lines"])
    read_file(result["output_file"])
```

### Example 3: Chained Operations
```python
# Step 1: Filter by time
time_result = run_time_slice(file, start, end, write_file=False)

# Step 2: Search in filtered results
if time_result["success"]:
    # Use filtered lines for further processing
    search_result = run_search_keyword(
        file, "error", write_file=True
    )
```
