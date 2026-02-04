# Filter Log Level Workflow Diagram

## Complete Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INPUT STAGE                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
            ┌───────▼───────┐ ┌────▼────┐ ┌────────▼────────┐
            │  File Path    │ │  String │ │  List of Lines  │
            │  (str path)   │ │ (str)   │ │    (List[str])  │
            └───────┬───────┘ └────┬────┘ └────────┬────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                            [Input Validation]
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       PROCESSING STAGE                                  │
└─────────────────────────────────────────────────────────────────────────┘

Step 1: Input Processing
    │
    ├─► If File Path → Read file → Split into lines
    ├─► If String → Split by newlines
    └─► If List → Use directly
    │
    ▼
Step 2: Normalize Log Levels
    │
    ├─► If single level (str) → Convert to list
    ├─► If multiple levels (list) → Use as is
    └─► Normalize all to UPPERCASE for matching
    │
    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    LOOP THROUGH EACH LINE                               │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ├─► Skip empty lines ──────┐
    │                          │
    │                          ▼
    │              ┌───────────────────────┐
    │              │ Extract Log Level     │
    │              │ _extract_log_level()  │
    │              └───────────┬───────────┘
    │                          │
    │                          ▼
    │          ┌───────────────────────────────┐
    │          │ LOG LEVEL FORMAT DETECTION    │
    │          └───────────┬──────────────────┘
    │                      │
    │      ┌────────────────┼────────────────┐
    │      │                │                │
    │      ▼                ▼                ▼
    │  ┌────────┐    ┌──────────┐    ┌──────────┐
    │  │Pattern │    │ Pattern  │    │ Pattern  │
    │  │   1    │    │    2     │    │    3     │
    │  │[ERROR] │    │ ERROR:  │    │ ERROR     │
    │  │[INFO]  │    │ INFO:   │    │ INFO     │
    │  └────┬───┘    └─────┬────┘    └─────┬────┘
    │       │              │                │
    │       └──────────────┼────────────────┘
    │                      │
    │      ┌────────────────┼────────────────┐
    │      │                │                │
    │      ▼                ▼                ▼
    │  ┌────────┐    ┌──────────┐    ┌──────────┐
    │  │Pattern │    │ Pattern  │    │ Pattern  │
    │  │   4    │    │    5     │    │    6     │
    │  │ERROR - │    │ ERROR   │    │After     │
    │  │INFO -  │    │(log4j)  │    │Timestamp │
    │  └────┬───┘    └─────┬────┘    └─────┬────┘
    │       │              │                │
    │       └──────────────┼────────────────┘
    │                      │
    │                      ▼
    │            ┌────────────────┐
    │            │ Log Level      │
    │            │ Found?         │
    │            └────┬───────┬───┘
    │                 │       │
    │              YES│       │NO
    │                 │       │
    │                 │       └───────────► Skip Line
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ Normalize to UPPERCASE    │
    │     │ (ERROR, INFO, DEBUG, etc.)│
    │     └───────────┬───────────────┘
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ Check if Level Matches:  │
    │     │ log_level in             │
    │     │ requested_levels         │
    │     └───────────┬───────────────┘
    │                 │
    │      ┌──────────┼──────────┐
    │      │          │          │
    │    YES│          │NO        │
    │      │          │          │
    │      │          └──────────► Skip Line
    │      │
    │      ▼
    │  ┌───────────────────────┐
    │  │ Add Line to Results   │
    │  │ filtered_lines.append()│
    │  └───────────┬───────────┘
    │              │
    └──────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          OUTPUT STAGE                                   │
└─────────────────────────────────────────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ▼          ▼          ▼
┌─────────────┐ ┌──────────────────┐ ┌──────────────────────┐
│  Option 1:  │ │   Option 2:      │ │   Option 3:          │
│  Return     │ │   Write to       │ │   Write to           │
│  List       │ │   Temp File      │ │   Specified File     │
│             │ │                  │ │                      │
│ filter_by_  │ │ filter_by_log_   │ │ filter_by_log_       │
│ log_level() │ │ level_to_file()  │ │ level_to_file()      │
│             │ │                  │ │ (with output_file)   │
│ Returns:    │ │ Returns:         │ │ Returns:             │
│ List[str]   │ │ temp_file.path   │ │ output_file.path     │
└─────────────┘ └──────────────────┘ └──────────────────────┘
```

## Detailed Component Breakdown

### 1. INPUT TYPES

```
┌─────────────────────────────────────────────┐
│              INPUT OPTIONS                  │
├─────────────────────────────────────────────┤
│                                             │
│  Option 1: File Path (str)                  │
│  ─────────────────────────                  │
│  Input: "/path/to/logfile.log"              │
│  Process: Read file → Split into lines      │
│                                             │
│  Option 2: String Content (str)             │
│  ────────────────────────────               │
│  Input: "[ERROR] Connection failed\n        │
│         [INFO] System started"              │
│  Process: Split by newlines                 │
│                                             │
│  Option 3: List of Lines (List[str])        │
│  ───────────────────────────────            │
│  Input: ["[ERROR] Log 1",                  │
│          "[INFO] Log 2"]                    │
│  Process: Use directly                      │
│                                             │
└─────────────────────────────────────────────┘
```

### 2. LOG LEVEL EXTRACTION PROCESS

```
┌────────────────────────────────────────────────────────────┐
│           _extract_log_level() Function                    │
└────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │                               │
        ▼                               ▼
┌───────────────┐           ┌───────────────────┐
│ Pattern-Based │           │  Format-Specific   │
│   Detection   │           │     Patterns      │
└───────┬───────┘           └─────────┬─────────┘
        │                             │
        ├─► Pattern 1: [ERROR]        ├─► Pattern 2: ERROR:
        │   [INFO]                   │   INFO:
        │   [DEBUG]                  │   DEBUG:
        │                            │
        ├─► Pattern 3: ERROR          ├─► Pattern 4: ERROR -
        │   INFO                     │   INFO -
        │   DEBUG                    │   DEBUG -
        │                            │
        ├─► Pattern 5: ERROR          ├─► Pattern 6: After Timestamp
        │   (log4j format)           │   2024-01-01 10:00:00 ERROR
        │   (multiple spaces)         │
        │                            │
        └─► Pattern 7: Word Boundary ├─► Fallback pattern
            (last resort)            │   Simple word match
        │
        ▼
┌──────────────────┐
│ Log Level Found? │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
   YES        NO
    │         │
    ▼         └───► Return None
 Normalize to
 UPPERCASE
    │
    ▼
 Return level
 (ERROR, INFO, etc.)
```

### 3. LOG LEVEL MATCHING

```
┌────────────────────────────────────────────────────────────┐
│              LOG LEVEL COMPARISON                          │
└────────────────────────────────────────────────────────────┘
                        │
            ┌───────────┼───────────┐
            │                       │
            ▼                       ▼
    ┌──────────────┐      ┌──────────────┐
    │ Requested    │      │  Extracted   │
    │ Log Levels   │      │  Log Level   │
    │ (normalized) │      │  (normalized)│
    └──────┬───────┘      └──────┬───────┘
           │                     │
           │  ['ERROR', 'FATAL'] │
           │                     │
           └──────────┬──────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  Check Condition:    │
          │                       │
          │ extracted_level in    │
          │ requested_levels     │
          └───────────┬───────────┘
                      │
           ┌──────────┼──────────┐
           │          │          │
         TRUE       FALSE        │
           │          │          │
           │          └──────────► Skip line
           │
           ▼
    ┌──────────────┐
    │ Include Line │
    │ in Results   │
    └──────────────┘
```

## Example Workflow

```
INPUT:
  log_content = "[ERROR] Connection failed
                 [INFO] System started
                 [WARN] Low memory
                 [DEBUG] Processing data
                 [ERROR] Timeout occurred"
  log_levels = ['ERROR', 'WARN']

PROCESSING:
  Line 1: "[ERROR] Connection failed"
    → Extract: ERROR
    → Compare: ERROR in ['ERROR', 'WARN'] ✅
    → Result: INCLUDE
  
  Line 2: "[INFO] System started"
    → Extract: INFO
    → Compare: INFO in ['ERROR', 'WARN'] ❌
    → Result: SKIP
  
  Line 3: "[WARN] Low memory"
    → Extract: WARN
    → Compare: WARN in ['ERROR', 'WARN'] ✅
    → Result: INCLUDE
  
  Line 4: "[DEBUG] Processing data"
    → Extract: DEBUG
    → Compare: DEBUG in ['ERROR', 'WARN'] ❌
    → Result: SKIP
  
  Line 5: "[ERROR] Timeout occurred"
    → Extract: ERROR
    → Compare: ERROR in ['ERROR', 'WARN'] ✅
    → Result: INCLUDE

OUTPUT:
  [
    "[ERROR] Connection failed",
    "[WARN] Low memory",
    "[ERROR] Timeout occurred"
  ]
```

## Supported Log Level Formats

The `_extract_log_level()` function supports 7 different pattern formats:

### Pattern 1: Bracket Format
```
[ERROR] Connection failed
[INFO] System started
[DEBUG] Processing data
```

### Pattern 2: Colon Format
```
ERROR: Connection failed
INFO: System started
DEBUG: Processing data
```

### Pattern 3: Space Format
```
ERROR Connection failed
INFO System started
DEBUG Processing data
```

### Pattern 4: Dash Format
```
ERROR - Connection failed
INFO - System started
DEBUG - Processing data
```

### Pattern 5: Log4j/SLF4J Format (Multiple Spaces)
```
2024-01-01 10:00:00 ERROR  Connection failed
2024-01-01 10:01:00 INFO   System started
2024-01-01 10:02:00 DEBUG  Processing data
```

### Pattern 6: After Timestamp Format
```
2024-01-01 10:00:00 ERROR Connection failed
2024-01-01T10:01:00 INFO System started
2024-01-01 10:02:00 DEBUG Processing data
```

### Pattern 7: Simple Word Boundary (Fallback)
```
This is an ERROR message
System INFO log entry
Debug information here
```

## Supported Log Levels

The function recognizes these standard log levels (case-insensitive):

1. **ERROR / ERR** - Error messages
2. **FATAL / CRITICAL** - Fatal/critical errors
3. **WARN / WARNING** - Warning messages
4. **INFO** - Informational messages
5. **DEBUG** - Debug messages
6. **TRACE** - Trace messages

## Output Options

The filter_log_level module provides **two output options**:

### Option 1: Return List (filter_by_log_level)
```python
filtered_lines = filter_by_log_level(log_content, 'ERROR')
# Returns: List[str] - list of filtered log lines
```

### Option 2: Write to File (filter_by_log_level_to_file)

**A) Write to Temporary File:**
```python
output_file = filter_by_log_level_to_file(log_content, 'ERROR')
# Returns: str - path to temporary .log file
```

**B) Write to Specified File:**
```python
output_file = filter_by_log_level_to_file(
    log_content, 
    ['ERROR', 'FATAL'], 
    output_file="error_logs.log"
)
# Returns: str - path to the output file
```

## Multiple Log Level Filtering

You can filter by multiple log levels at once:

```python
# Filter ERROR and FATAL logs
critical_logs = filter_by_log_level(log_content, ['ERROR', 'FATAL'])

# Filter all warning and error levels
alert_logs = filter_by_log_level(log_content, ['ERROR', 'FATAL', 'WARN', 'WARNING'])
```

## Key Features

✅ **Multiple Input Types**: File path, string, or list  
✅ **Multiple Output Options**: Return list or write to file  
✅ **7 Pattern Formats**: Automatic format detection  
✅ **Case-Insensitive**: Works with ERROR, error, Error, etc.  
✅ **Multiple Levels**: Filter by one or multiple log levels  
✅ **Standard Levels**: ERROR, FATAL, WARN, INFO, DEBUG, TRACE  
✅ **Flexible Matching**: Handles various log format conventions  
✅ **No External Dependencies**: Uses only Python standard library

## Log Level Priority

When multiple log levels are found in a line, the function prioritizes:
1. ERROR / FATAL / CRITICAL (highest priority)
2. WARN / WARNING
3. INFO
4. DEBUG
5. TRACE (lowest priority)

This ensures that critical levels are detected even if multiple levels appear in the same line.

---

## AI Agent Integration: run_filter_log_level()

For AI agent integration, use the `run_filter_log_level()` function which returns structured dictionaries instead of printing results.

### Function Signature

```python
def run_filter_log_level(
    file_path: str,
    log_levels: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True
) -> Dict
```

### Return Structure

```python
{
    "success": bool,
    "filtered_lines": List[str],      # All filtered lines combined
    "output_files": List[str],        # One file per level
    "counts_by_level": Dict[str, int], # Count of lines per level
    "error": str | None
}
```

### Usage Example

```python
from utilities.filter_log_level import run_filter_log_level

# Filter by single level
result = run_filter_log_level("logs/app.log", "ERROR")

if result["success"]:
    print(f"Found {len(result['filtered_lines'])} error lines")
    print(f"Created {len(result['output_files'])} output files")
    for level, count in result["counts_by_level"].items():
        print(f"  {level}: {count} lines")
else:
    print(f"Error: {result['error']}")

# Filter by multiple levels
result = run_filter_log_level(
    "logs/app.log",
    ["ERROR", "FATAL", "WARN"],
    output_dir="custom_output",
    write_file=True
)

# Process without writing files
result = run_filter_log_level(
    "logs/app.log",
    "ERROR",
    write_file=False  # Returns data without creating files
)
```

### Key Differences from filter_by_log_level()

| Feature | filter_by_log_level() | run_filter_log_level() |
|---------|----------------------|------------------------|
| Input | File path, string, or list | File path only |
| Output | List of lines | Dictionary with structured data |
| File Writing | Separate function needed | Built-in with `write_file` option |
| Error Handling | Raises exceptions | Returns error in dictionary |
| AI Agent Ready | ❌ | ✅ |
| CLI Usage | ✅ | ✅ |
