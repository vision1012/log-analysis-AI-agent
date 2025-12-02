# Time Slice Workflow Diagram

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
┌─────────────────────────────────────────────────────────────────────────┐
│                    LOOP THROUGH EACH LINE                               │
└─────────────────────────────────────────────────────────────────────────┘
    │
    ├─► Skip empty lines ──────┐
    │                          │
    │                          ▼
    │              ┌───────────────────────┐
    │              │ Extract Timestamp     │
    │              │ _extract_timestamp()  │
    │              └───────────┬───────────┘
    │                          │
    │                          ▼
    │          ┌───────────────────────────────┐
    │          │ TIMESTAMP FORMAT DETECTION    │
    │          └───────────┬───────────────────┘
    │                      │
    │      ┌───────────────┼───────────────┬───────────────┐
    │      │               │               │               │
    │      ▼               ▼               ▼               ▼
    │  ┌────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐
    │  │  Unix  │    │   ISO   │    │  Apache  │    │  Syslog  │
    │  │  Timestamp│  │  8601   │    │  Format  │    │  Format  │
    │  └────┬───┘    └────┬────┘    └─────┬────┘    └─────┬────┘
    │       │             │               │               │
    │       └─────────────┼───────────────┼───────────────┘
    │                     │               │
    │      ┌──────────────┼───────────────┼──────────────┐
    │      │              │               │              │
    │      ▼              ▼               ▼              ▼
    │  ┌────────┐   ┌──────────┐   ┌──────────┐  ┌──────────┐
    │  │  RFC   │   │  Bracket │   │    US    │  │ European │
    │  │  2822  │   │  Format  │   │   Date   │  │   Date   │
    │  └────┬───┘   └─────┬────┘   └─────┬────┘  └─────┬────┘
    │       │             │               │             │
    │       └─────────────┼───────────────┼─────────────┘
    │                     │               │
    │      ┌──────────────┼───────────────┼──────────────┐
    │      │              │               │              │
    │      ▼              ▼               ▼              ▼
    │  ┌────────┐   ┌──────────┐   ┌──────────┐  ┌──────────┐
    │  │  Time  │   │   12-Hour│   │Milliseconds│ │  Custom  │
    │  │  Only  │   │  Format  │   │   Format  │ │  Format  │
    │  └────┬───┘   └─────┬────┘   └─────┬────┘  └─────┬────┘
    │       │             │               │             │
    │       └─────────────┼───────────────┼─────────────┘
    │                     │               │
    │                     ▼               │
    │            [Parse Timestamp]        │
    │                     │               │
    │                     ▼               │
    │            ┌────────────────┐       │
    │            │ Timestamp Found?│       │
    │            └────┬───────┬───┘       │
    │                 │       │           │
    │              YES│       │NO         │
    │                 │       │           │
    │                 │       └───────────► Skip Line
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ Convert Timezone-Aware    │
    │     │ to Naive (if needed)      │
    │     └───────────┬───────────────┘
    │                 │
    │                 ▼
    │     ┌───────────────────────────┐
    │     │ Check Time Range:         │
    │     │ start_time <= timestamp   │
    │     │           <= end_time     │
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
│ slice_by_   │ │ slice_by_time_   │ │ slice_by_time_       │
│ time()      │ │ to_file()        │ │ to_file()            │
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
│  Input: "2024-01-01T10:00:00 log1\n        │
│         2024-01-01T11:00:00 log2"          │
│  Process: Split by newlines                 │
│                                             │
│  Option 3: List of Lines (List[str])        │
│  ───────────────────────────────            │
│  Input: ["2024-01-01T10:00:00 log1",       │
│          "2024-01-01T11:00:00 log2"]       │
│  Process: Use directly                      │
│                                             │
└─────────────────────────────────────────────┘
```

### 2. TIMESTAMP EXTRACTION PROCESS

```
┌────────────────────────────────────────────────────────────┐
│           _extract_timestamp() Function                    │
└────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │                               │
        ▼                               ▼
┌───────────────┐           ┌───────────────────┐
│ Unix Timestamp│           │  Format-Specific  │
│   Detection   │           │     Patterns      │
└───────┬───────┘           └─────────┬─────────┘
        │                             │
        ├─► 13 digits (ms)            ├─► ISO 8601
        │   → ÷ 1000 → datetime       │   → Parse with formats
        │                             │
        └─► 10 digits (seconds)       ├─► Apache/Nginx
            → datetime                │   → [DD/MMM/YYYY:HH:MM:SS]
                                      │
                                      ├─► Syslog
                                      │   → MMM DD HH:MM:SS
                                      │
                                      ├─► RFC 2822
                                      │   → Day, DD MMM YYYY HH:MM:SS
                                      │
                                      ├─► Bracket Format
                                      │   → [YYYY-MM-DD HH:MM:SS]
                                      │
                                      ├─► US Date Format
                                      │   → MM/DD/YYYY HH:MM:SS
                                      │
                                      ├─► European Date Format
                                      │   → DD-MM-YYYY HH:MM:SS
                                      │
                                      ├─► Time Only
                                      │   → HH:MM:SS
                                      │
                                      └─► 12-Hour Format
                                          → HH:MM:SS AM/PM
        │
        ▼
┌──────────────────┐
│ Timestamp Found? │
└────────┬─────────┘
         │
    ┌────┴────┐
    │         │
   YES        NO
    │         │
    ▼         └───► Return None
 Return datetime
```

### 3. TIME RANGE FILTERING

```
┌────────────────────────────────────────────────────────────┐
│              TIME RANGE COMPARISON                         │
└────────────────────────────────────────────────────────────┘
                        │
            ┌───────────┼───────────┐
            │                       │
            ▼                       ▼
    ┌──────────────┐      ┌──────────────┐
    │  start_time  │      │   end_time   │
    │  (datetime)  │      │  (datetime)  │
    └──────┬───────┘      └──────┬───────┘
           │                     │
           └──────────┬──────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │  timestamp extracted  │
          │    from log line      │
          └───────────┬───────────┘
                      │
                      ▼
          ┌───────────────────────┐
          │   Check Condition:    │
          │                       │
          │ start_time <=         │
          │ timestamp <=          │
          │ end_time              │
          └───────────┬───────────┘
                      │
           ┌──────────┼──────────┐
           │          │          │
         TRUE       FALSE       │
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
  log_content = "2024-01-01T09:30:00 Early log
                 2024-01-01T10:15:00 Middle log
                 2024-01-01T10:45:00 Later log
                 2024-01-01T11:30:00 Late log"
  start_time = datetime(2024, 1, 1, 10, 0, 0)
  end_time = datetime(2024, 1, 1, 11, 0, 0)

PROCESSING:
  Line 1: "2024-01-01T09:30:00 Early log"
    → Extract: 2024-01-01 09:30:00
    → Compare: 09:30:00 < 10:00:00 ❌
    → Result: SKIP
  
  Line 2: "2024-01-01T10:15:00 Middle log"
    → Extract: 2024-01-01 10:15:00
    → Compare: 10:00:00 <= 10:15:00 <= 11:00:00 ✅
    → Result: INCLUDE
  
  Line 3: "2024-01-01T10:45:00 Later log"
    → Extract: 2024-01-01 10:45:00
    → Compare: 10:00:00 <= 10:45:00 <= 11:00:00 ✅
    → Result: INCLUDE
  
  Line 4: "2024-01-01T11:30:00 Late log"
    → Extract: 2024-01-01 11:30:00
    → Compare: 11:30:00 > 11:00:00 ❌
    → Result: SKIP

OUTPUT:
  [
    "2024-01-01T10:15:00 Middle log",
    "2024-01-01T10:45:00 Later log"
  ]
```

## Supported Timestamp Formats

The `_extract_timestamp()` function supports 15+ timestamp formats:

1. **Unix Timestamps**
   - 10 digits (seconds): `1704110400`
   - 13 digits (milliseconds): `1704110400000`

2. **ISO 8601**
   - `2024-01-01T10:00:00`
   - `2024-01-01T10:00:00.123456`
   - `2024-01-01T10:00:00Z`
   - `2024-01-01T10:00:00+05:30`
   - `2024-01-01 10:00:00`

3. **Apache/Nginx**
   - `[01/Jan/2024:10:00:00 +0000]`

4. **Syslog**
   - `Jan 1 10:00:00`
   - `Jan  1 10:00:00` (double space)

5. **RFC 2822**
   - `Mon, 01 Jan 2024 10:00:00 +0000`

6. **Bracket Format**
   - `[2024-01-01 10:00:00]`
   - `[2024-01-01 10:00:00.123]`

7. **Date Formats**
   - US: `01/01/2024 10:00:00`
   - European: `01-01-2024 10:00:00`
   - ISO-like: `2024/01/01 10:00:00`

8. **Time Only**
   - `10:00:00` (uses current date)
   - `10:00:00 AM` / `10:00:00 PM`

## Output Options

The time_slice module provides **two output options**:

### Option 1: Return List (slice_by_time)
```python
filtered_lines = slice_by_time(log_content, start_time, end_time)
# Returns: List[str] - list of filtered log lines
```

### Option 2: Write to File (slice_by_time_to_file)

**A) Write to Temporary File:**
```python
output_file = slice_by_time_to_file(log_content, start_time, end_time)
# Returns: str - path to temporary .log file
```

**B) Write to Specified File:**
```python
output_file = slice_by_time_to_file(
    log_content, 
    start_time, 
    end_time, 
    output_file="filtered_logs.log"
)
# Returns: str - path to the output file
```

## Key Features

✅ **Multiple Input Types**: File path, string, or list  
✅ **Multiple Output Options**: Return list or write to file  
✅ **15+ Timestamp Formats**: Automatic format detection  
✅ **Timezone Handling**: Converts timezone-aware to naive  
✅ **Inclusive Boundaries**: Start and end times are inclusive  
✅ **Robust Parsing**: Handles edge cases and invalid formats  
✅ **Empty Line Handling**: Skips empty lines automatically  
✅ **No External Dependencies**: Uses only Python standard library

