# Documentation Index

## Overview

This directory contains comprehensive documentation for the Log Analysis AI Agent project, including architecture diagrams, workflow documentation, and API references.

## Documentation Files

### Architecture Documentation

1. **architecture_overview.md**
   - Complete system architecture
   - Three-layer architecture explanation
   - Function categories and integration points
   - Data flow diagrams
   - Error handling patterns
   - Future enhancements

2. **architecture_diagram.md**
   - Visual architecture diagrams
   - Data flow diagrams
   - Function call hierarchy
   - File organization structure
   - Return dictionary structure
   - Integration examples

3. **run_functions_api.md**
   - Complete API reference for all `run_*()` functions
   - Function signatures and parameters
   - Return structures
   - Usage examples
   - Error handling patterns
   - Best practices

### Workflow Documentation

4. **time_slice_workflow.md**
   - Complete workflow for time-based log slicing
   - Timestamp format detection
   - Input/output options
   - `run_time_slice()` function documentation
   - Usage examples

5. **filter_log_level_workflow.md**
   - Complete workflow for log level filtering
   - Log level pattern matching
   - Multiple level filtering
   - `run_filter_log_level()` function documentation
   - Usage examples

6. **error_code_workflow.md**
   - Complete workflow for error code extraction and search
   - Error code pattern detection
   - Search and extraction methods
   - Usage examples

### Visual Assets

7. **Log-Agent-RAG.png**
   - RAG (Retrieval-Augmented Generation) architecture diagram
   - Visual representation of the AI agent system

## Quick Start Guide

### For Developers

1. Start with **architecture_overview.md** to understand the system structure
2. Review **architecture_diagram.md** for visual representations
3. Check **run_functions_api.md** for function reference

### For AI Agent Integration

1. Read **run_functions_api.md** for complete API reference
2. Review **architecture_overview.md** for integration patterns
3. Check individual workflow docs for specific use cases

### For CLI Users

1. Review workflow documentation for specific utilities:
   - **time_slice_workflow.md** for time-based filtering
   - **filter_log_level_workflow.md** for level filtering
   - **error_code_workflow.md** for error code operations

## Function Categories

### Core Functions (AI Agent Ready)

All `run_*()` functions are designed for programmatic use:

- `run_time_slice()` - Slice logs by time range
- `run_search_keyword()` - Search by keyword(s)
- `run_filter_log_level()` - Filter by log level(s)
- `run_log_summary()` - Generate log summary
- `run_stacktrace()` - Extract stacktraces
- `run_error_code_search()` - Search by error code(s)
- `run_error_code_extract_all()` - Extract all error codes
- `run_error_lines()` - Extract error lines

### Utility Functions

Core processing functions (can be called directly):

- `slice_by_time()` - Core time slicing logic
- `search_keyword()` - Core keyword search logic
- `filter_by_log_level()` - Core level filtering logic
- `summarize_log()` - Core summary generation
- `extract_stacktraces()` - Core stacktrace extraction
- `extract_all_error_codes()` - Core error code extraction
- `get_error_lines()` - Core error line extraction

### Interactive Functions

CLI convenience wrappers:

- `interactive_slice_by_time()` - Interactive time slicing
- `interactive_filter_by_log_level()` - Interactive level filtering
- `interactive_search_by_error_code()` - Interactive error code search

## Documentation Structure

```
docs/
├── README.md (this file)
├── architecture_overview.md      # System architecture
├── architecture_diagram.md       # Visual diagrams
├── run_functions_api.md          # API reference
├── time_slice_workflow.md        # Time slicing workflow
├── filter_log_level_workflow.md  # Log level filtering workflow
├── error_code_workflow.md        # Error code workflow
└── Log-Agent-RAG.png            # Visual diagram
```

## Key Concepts

### Three-Layer Architecture

1. **Interface Layer**: CLI, Interactive, API
2. **Core Layer**: `run_*()` functions (AI-ready)
3. **Utility Layer**: Core processing functions

### Dictionary Returns

All `run_*()` functions return structured dictionaries:

```python
{
    "success": bool,
    "error": str | None,
    "output_file": str | None,
    # ... function-specific fields
}
```

### Error Handling

Consistent error handling across all functions:
- Validation errors return `success=False` with error message
- Processing errors caught and returned in dictionary
- No exceptions raised (except for programming errors)

## Testing

- **303 total tests** across 5 test files
- **34 new tests** for `run_*()` functions
- All tests passing ✅

See `code_testing/` directory for test files.

## Contributing

When adding new utilities:

1. Create core processing function
2. Create `run_*()` wrapper function
3. Add to `log_utility_main.py` menu
4. Create workflow documentation
5. Add comprehensive tests
6. Update this README

## Related Files

- `utilities/` - All utility implementations
- `code_testing/` - Test files
- `README.md` - Main project README
