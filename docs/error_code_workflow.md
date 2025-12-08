# Error Code Search Workflow Diagram

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
Step 2: Normalize Error Codes (if searching)
    │
    ├─► If single code (str) → Convert to list
    ├─► If multiple codes (list) → Use as is
    └─► Normalize based on case_sensitive flag
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
    │              │ Extract Error Codes  │
    │              │ _extract_error_codes_ │
    │              │ from_line()           │
    │              └───────────┬───────────┘
    │                          │
    │                          ▼
    │          ┌───────────────────────────────┐
    │          │ ERROR CODE PATTERN DETECTION │
    │          └───────────┬──────────────────┘
    │                      │
    │      ┌───────────────┼───────────────┬───────────────┐
    │      │               │               │               │
    │      ▼               ▼               ▼               ▼
    │  ┌────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  │Pattern │    │ Pattern  │    │ Pattern  │    │ Pattern  │
    │  │   1    │    │    2     │    │    3     │    │    4     │
    │  │  HTTP  │    │ STANDARD │    │ NUMERIC  │    │  CUSTOM  │
    │  │ STATUS │    │   CODE   │    │   CODE   │    │   CODE   │
    │  │  503   │    │ ERR001   │    │ error:   │    │ ERROR_   │
    │  │  404   │    │ DB1001E  │    │ 1001     │    │ 500      │
    │  └────┬───┘    └─────┬────┘    └─────┬────┘    └─────┬────┘
    │       │             │               │               │
    │       └─────────────┼───────────────┼───────────────┘
    │                     │               │
    │      ┌──────────────┼───────────────┼──────────────┐
    │      │              │               │              │
    │      ▼              ▼               ▼              ▼
    │  ┌────────┐    ┌──────────┐    ┌──────────┐  ┌──────────┐
    │  │Pattern │    │ Pattern  │    │ Pattern  │  │  False   │
    │  │   5    │    │    6     │    │ Positive │  │ Positive │
    │  │   HEX  │    │ EXCEPTION│    │ Filter   │  │ Filter   │
    │  │ 0x8000 │    │   CODE   │    │ (avoid   │  │ (avoid   │
    │  │        │    │Exception:│    │timestamps)│  │millisec) │
    │  └────┬───┘    └─────┬────┘    └─────┬────┘  └─────┬────┘
    │       │             │               │              │
    │       └─────────────┼───────────────┼──────────────┘
    │                     │               │
    │                     ▼               │
    │            ┌────────────────┐       │
    │            │ Error Code     │       │
    │            │ Found?         │       │
    │            └────┬───────┬───┘       │
    │                 │       │           │
    │              YES│       │NO         │
    │                 │       │           │
    │                 │       └───────────► Skip Line
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ Extract Metadata:        │
    │     │ - Timestamp               │
    │     │ - Log Level               │
    │     │ - Line Number             │
    │     │ - Pattern Type            │
    │     └───────────┬───────────────┘
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ MODE: Search or Extract?  │
    │     └───────────┬───────────────┘
    │                 │
    │      ┌──────────┼──────────┐
    │      │          │          │
    │   SEARCH│    EXTRACT│      │
    │      │          │          │
    │      ▼          ▼          │
    │  ┌────────┐ ┌──────────┐  │
    │  │ Check  │ │ Store in │  │
    │  │ if code│ │ Summary  │  │
    │  │ matches│ │ Stats    │  │
    │  │ search │ └──────────┘  │
    │  │ codes  │               │
    │  └───┬────┘               │
    │      │                    │
    │      ▼                    │
    │  ┌──────────────┐          │
    │  │ Match Found?│          │
    │  └────┬─────┬──┘          │
    │       │     │             │
    │     YES│     │NO          │
    │       │     │             │
    │       │     └─────────────► Skip Line
    │       │
    │       ▼
    │  ┌───────────────────────┐
    │  │ Add Line to Results   │
    │  │ matched_lines.append()│
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
│ search_by_  │ │ search_by_error_ │ │ search_by_error_    │
│ error_code()│ │ code_to_file()   │ │ code_to_file()      │
│             │ │                  │ │ (with output_file)   │
│ Returns:    │ │ Returns:         │ │ Returns:             │
│ List[str]   │ │ temp_file.path   │ │ output_file.path     │
└─────────────┘ └──────────────────┘ └──────────────────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │   Option 4:          │
        │   Extract All        │
        │   with Summary       │
        │                      │
        │ extract_all_error_   │
        │ codes()              │
        │                      │
        │ Returns:             │
        │ (matches, summary)   │
        └──────────────────────┘
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
│  Input: "[ERROR] HTTP Status 503\n          │
│         [ERROR] Error code: ERR001"         │
│  Process: Split by newlines                 │
│                                             │
│  Option 3: List of Lines (List[str])        │
│  ───────────────────────────────            │
│  Input: ["[ERROR] HTTP Status 503",         │
│          "[ERROR] Error code: ERR001"]      │
│  Process: Use directly                      │
│                                             │
└─────────────────────────────────────────────┘
```

### 2. ERROR CODE EXTRACTION PROCESS

```
┌────────────────────────────────────────────────────────────┐
│      _extract_error_codes_from_line() Function           │
└────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │                               │
        ▼                               ▼
┌───────────────┐           ┌───────────────────┐
│ Pattern-Based │           │  Context-Aware   │
│   Detection   │           │     Filtering     │
└───────┬───────┘           └─────────┬─────────┘
        │                             │
        ├─► Pattern 1: HTTP Status   ├─► Filter timestamps
        │   → 100-599                 │   → Avoid .567, .345
        │   → "HTTP Status 503"       │   → Check for HH:MM:SS
        │   → "Status 404"            │
        │                             │
        ├─► Pattern 2: Standard      ├─► Filter false positives
        │   → ERR001, DB1001E         │   → Avoid HTTP, STATUS
        │   → [A-Z]{2,6}\d{3,4}[EI]   │   → Require letters+digits
        │                             │
        ├─► Pattern 3: Numeric        ├─► Validate context
        │   → "error: 1001"           │   → Check surrounding text
        │   → "code: 500"             │   → Verify error context
        │                             │
        ├─► Pattern 4: Custom         │
        │   → ERROR_500               │
        │   → DB-1001                 │
        │   → AUTH_ERR_001            │
        │                             │
        ├─► Pattern 5: Hexadecimal    │
        │   → 0x80004005              │
        │   → 0xFF                    │
        │                             │
        └─► Pattern 6: Exception Code │
            → DatabaseException: 1001 │
            → Error: 500              │
        │
        ▼
┌──────────────────┐
│ Codes Found?     │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
   YES        NO
    │         │
    ▼         └───► Return empty list
 Return list of
 (code, pattern_type)
 tuples
```

### 3. ERROR CODE PATTERN MATCHING

```
┌────────────────────────────────────────────────────────────┐
│              ERROR CODE COMPARISON                         │
└────────────────────────────────────────────────────────────┘
                        │
            ┌───────────┼───────────┐
            │                       │
            ▼                       ▼
    ┌──────────────┐      ┌──────────────┐
    │ Requested    │      │  Extracted   │
    │ Error Codes  │      │  Error Codes │
    │ (normalized) │      │  (from line) │
    └──────┬───────┘      └──────┬───────┘
           │                     │
           │  ['503', '404']     │
           │                     │
           └──────────┬──────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  Check Condition:     │
          │                       │
          │ extracted_code in     │
          │ requested_codes       │
          │                       │
          │ (case-sensitive flag) │
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

### Example 1: Search for Specific Error Code

```
INPUT:
  log_content = "2025-12-02 12:01:05.012 [ERROR] Payment gateway failed: HTTP Status 503
                 2025-12-02 12:02:00.123 [ERROR] Database connection error: DB1001E
                 2025-12-02 12:03:00.456 [ERROR] Authentication failed: AUTH_ERR_001
                 2025-12-02 12:04:00.567 [ERROR] File not found: error code 404"
  error_codes = ['503', '404']

PROCESSING:
  Line 1: "2025-12-02 12:01:05.012 [ERROR] Payment gateway failed: HTTP Status 503"
    → Extract: 503 (HTTP_STATUS pattern)
    → Compare: 503 in ['503', '404'] ✅
    → Result: INCLUDE
  
  Line 2: "2025-12-02 12:02:00.123 [ERROR] Database connection error: DB1001E"
    → Extract: DB1001E (STANDARD pattern)
    → Compare: DB1001E in ['503', '404'] ❌
    → Result: SKIP
  
  Line 3: "2025-12-02 12:03:00.456 [ERROR] Authentication failed: AUTH_ERR_001"
    → Extract: AUTH_ERR_001 (CUSTOM pattern)
    → Compare: AUTH_ERR_001 in ['503', '404'] ❌
    → Result: SKIP
  
  Line 4: "2025-12-02 12:04:00.567 [ERROR] File not found: error code 404"
    → Extract: 404 (NUMERIC pattern - "error code 404")
    → Compare: 404 in ['503', '404'] ✅
    → Result: INCLUDE

OUTPUT:
  [
    "2025-12-02 12:01:05.012 [ERROR] Payment gateway failed: HTTP Status 503",
    "2025-12-02 12:04:00.567 [ERROR] File not found: error code 404"
  ]
```

### Example 2: Extract All Error Codes

```
INPUT:
  log_content = "2025-12-02 12:01:05.012 [ERROR] HTTP Status 503
                 2025-12-02 12:02:00.123 [ERROR] Error code: ERR001
                 2025-12-02 12:03:00.456 [ERROR] Database error: DB-1001
                 2025-12-02 12:04:00.567 [ERROR] System error: 0x80004005"

PROCESSING:
  Line 1: Extract → 503 (HTTP_STATUS)
  Line 2: Extract → ERR001 (STANDARD)
  Line 3: Extract → DB-1001 (CUSTOM)
  Line 4: Extract → 0x80004005 (HEX)

OUTPUT SUMMARY:
  Total Matches: 4
  Unique Codes: 4
  Codes by Frequency:
    503: 1 occurrence
    ERR001: 1 occurrence
    DB-1001: 1 occurrence
    0x80004005: 1 occurrence
  Codes by Type:
    HTTP_STATUS: [503]
    STANDARD: [ERR001]
    CUSTOM: [DB-1001]
    HEX: [0x80004005]
```

## Supported Error Code Patterns

The `_extract_error_codes_from_line()` function supports 6 different pattern types:

### Pattern 1: HTTP Status Codes
```
HTTP Status 503 Service Unavailable
Status 404 Not Found
HTTP 500 Internal Server Error
503 Service Unavailable
```
- **Pattern**: `(?:HTTP\s+)?(?:Status\s+)?([1-5]\d{2})`
- **Range**: 100-599
- **Context-aware**: Avoids matching timestamps (e.g., .503 milliseconds)

### Pattern 2: Standard Error Codes
```
ERR001 - Standard error format
DB1001E - Database error with E suffix
AUTH500I - Authentication error with I suffix
NET2001E - Network error code
```
- **Pattern**: `([A-Z]{2,6}\d{3,4}[EI])`
- **Format**: 2-6 uppercase letters + 3-4 digits + E or I suffix
- **Examples**: ERR001, DB1001E, AUTH500I

### Pattern 3: Numeric Error Codes with Prefix
```
error: 1001
code: 500
err: 404
Error 2001
```
- **Pattern**: `(?:error|code|err)[\s:]+([A-Z]?\d{3,6})`
- **Format**: "error"/"code"/"err" keyword + colon/space + 3-6 digit code
- **Context-aware**: Validates not part of timestamp

### Pattern 4: Custom Codes with Separators
```
ERROR_500 - Underscore separator
DB-1001 - Dash separator
AUTH_ERR_001 - Multiple separators
PAYMENT-5000 - Custom format
```
- **Pattern**: `([A-Z]{2,}[_-]\d{3,6})`
- **Format**: 2+ uppercase letters + underscore/dash + 3-6 digits
- **Filter**: Excludes common false positives (HTTP, STATUS)

### Pattern 5: Hexadecimal Codes
```
0x80004005 - Windows error code
0xFF - Single byte code
0xDEADBEEF - Custom hex code
```
- **Pattern**: `(0x[0-9A-Fa-f]{2,8})`
- **Format**: 0x prefix + 2-8 hexadecimal digits
- **Case**: Normalized to uppercase

### Pattern 6: Exception Codes
```
DatabaseException: 1001
NullPointerError: 500
FileNotFoundException: 404
```
- **Pattern**: `([A-Z][a-zA-Z]+Exception|Error)\s*[:\s]+([A-Z]?\d{3,6})`
- **Format**: Exception/Error class name + colon/space + numeric code
- **Extracts**: The numeric code part

## False Positive Filtering

The system includes intelligent filtering to avoid false positives:

### Timestamp Filtering
```
❌ AVOID: 2025-12-02 12:04:00.567 (567 is milliseconds, not error code)
✅ MATCH: HTTP Status 503 (503 is clearly an HTTP status code)
```

### Context Validation
```
❌ AVOID: "Processing 500 items" (500 is a quantity, not error code)
✅ MATCH: "error: 500" (500 is clearly an error code)
```

### Pattern Validation
```
❌ AVOID: "HTTP" or "STATUS" as error codes
✅ MATCH: "ERROR_500" or "DB-1001" (valid custom codes)
```

## Output Options

The error_code module provides **four output options**:

### Option 1: Return List (search_by_error_code)
```python
matched_lines = search_by_error_code(log_content, '503')
# Returns: List[str] - list of matching log lines
```

### Option 2: Write to Temporary File
```python
output_file = search_by_error_code_to_file(log_content, '503')
# Returns: str - path to temporary .log file
```

### Option 3: Write to Specified File
```python
output_file = search_by_error_code_to_file(
    log_content, 
    ['503', '404'], 
    output_file="error_codes.log"
)
# Returns: str - path to the output file
```

### Option 4: Extract All with Summary
```python
matches, summary = extract_all_error_codes(log_content)
# Returns: (List[ErrorCodeMatch], ErrorCodeSummary)
# - matches: List of all error code matches with metadata
# - summary: Statistics including frequency, types, and details
```

## Multiple Error Code Search

You can search for multiple error codes at once:

```python
# Search for multiple HTTP status codes
http_errors = search_by_error_code(log_content, ['503', '404', '500'])

# Search for mixed code types
all_errors = search_by_error_code(log_content, ['503', 'ERR001', 'DB-1001'])

# Case-sensitive search
exact_match = search_by_error_code(log_content, ['Error_500'], case_sensitive=True)
```

## Interactive Mode

The `interactive_search_by_error_code()` function provides an interactive CLI:

```bash
python utilities/error_code.py logfile.log
```

**Features:**
- Automatically scans and displays available error codes
- Shows top 20 most frequent codes
- Allows selection by code or index number
- Supports comma/space-separated input
- Creates output files in `output/` directory

**Example Interactive Session:**
```
============================================================
ERROR CODE SEARCH - Interactive Mode
============================================================

Processing file: output/data_ERROR.log

Scanning for error codes...

✓ Found 3 unique error code(s) in the log file.

Available error codes (top 20):
   1. 503                  (1 occurrence(s))
   2. ERR001               (1 occurrence(s))
   3. DB-1001              (1 occurrence(s))

Enter error code(s) to search for:
  - Comma-separated or space-separated: 503, 404, ERR001
  - Or enter numbers from the list above: 1,2,3
  - Type 'all' to extract all error codes
  - Type 'summary' to see detailed summary
  - Type 'quit' to exit

Your selection: 1,2
```

## Command-Line Usage

### Basic Search
```bash
python utilities/error_code.py logfile.log 503
```

### Multiple Codes
```bash
python utilities/error_code.py logfile.log "503, 404, ERR001"
```

### Extract All Codes
```bash
python utilities/error_code.py logfile.log --extract-all
```

### Show Summary
```bash
python utilities/error_code.py logfile.log --summary
```

### Interactive Mode
```bash
python utilities/error_code.py logfile.log
# (no error codes specified = interactive mode)
```

## Key Features

✅ **Multiple Input Types**: File path, string, or list  
✅ **Multiple Output Options**: Return list, write to file, or extract with summary  
✅ **6 Pattern Types**: HTTP status, standard, numeric, custom, hex, exception codes  
✅ **Case-Insensitive Search**: Works with 503, Error_500, etc.  
✅ **False Positive Filtering**: Avoids matching timestamps and quantities  
✅ **Context-Aware Detection**: Validates error context before matching  
✅ **Multiple Codes**: Search for one or multiple error codes  
✅ **Summary Statistics**: Frequency, types, and detailed information  
✅ **Interactive Mode**: User-friendly CLI with code discovery  
✅ **Standard & Custom Codes**: Handles both standard and internal error codes  
✅ **Metadata Extraction**: Timestamps, log levels, line numbers  
✅ **No External Dependencies**: Uses only Python standard library (optional dateutil)

## Error Code Type Classification

Error codes are automatically classified by pattern type:

1. **HTTP_STATUS** - HTTP status codes (100-599)
2. **STANDARD** - Standard format codes (e.g., ERR001, DB1001E)
3. **NUMERIC** - Numeric codes with error/code prefix
4. **CUSTOM** - Custom internal codes with separators
5. **HEX** - Hexadecimal error codes
6. **EXCEPTION_CODE** - Codes associated with exceptions

## Summary Statistics

The `ErrorCodeSummary` dataclass provides:

- **total_matches**: Total number of error code occurrences
- **unique_codes**: Number of unique error codes found
- **codes_by_frequency**: Dictionary mapping codes to occurrence counts
- **codes_by_type**: Dictionary mapping pattern types to code lists
- **code_details**: Dictionary mapping codes to first occurrence details

## Integration with Other Features

The error code search integrates seamlessly with other log analysis features:

```python
# Combine with log level filtering
error_logs = filter_by_log_level(log_content, 'ERROR')
error_codes = search_by_error_code(error_logs, '503')

# Combine with time slicing
time_filtered = slice_by_time(log_content, start_time, end_time)
codes_in_timeframe = extract_all_error_codes(time_filtered)

# Combine with keyword search
keyword_results = search_keyword(log_content, 'payment')
payment_errors = search_by_error_code(keyword_results, ['503', '500'])
```
