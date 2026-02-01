import re
import os
import tempfile
from datetime import datetime
from typing import Union, List, Dict, Optional, Tuple
from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class ErrorCodeMatch:
    """Represents a single error code match in a log line."""
    code: str
    line_number: int
    line_content: str
    timestamp: Optional[datetime] = None
    log_level: Optional[str] = None
    context: str = ""


@dataclass
class ErrorCodeSummary:
    """Summary statistics for error codes found in logs."""
    total_matches: int
    unique_codes: int
    codes_by_frequency: Dict[str, int]
    codes_by_type: Dict[str, List[str]]
    code_details: Dict[str, ErrorCodeMatch]


# Standard error code patterns
# HTTP status codes: Match 100-599, but avoid matching timestamps (e.g., not after colons in time format)
HTTP_STATUS_PATTERN = re.compile(r'\b(?:HTTP\s+)?(?:Status\s+)?([1-5]\d{2})\b(?!\s*[:\d])', re.IGNORECASE)
STANDARD_ERROR_PATTERN = re.compile(r'\b([A-Z]{2,6}\d{3,4}[EI])\b')  # Like ERR001, DB1001E
NUMERIC_ERROR_PATTERN = re.compile(r'\b(?:error|code|err)[\s:]+([A-Z]?\d{3,6})\b', re.IGNORECASE)
CUSTOM_CODE_PATTERN = re.compile(r'\b([A-Z]{2,}[_-]\d{3,6})\b')  # Like ERROR_500, DB-1001 (requires separator)
HEX_CODE_PATTERN = re.compile(r'\b(0x[0-9A-Fa-f]{2,8})\b')  # Hexadecimal codes
EXCEPTION_CODE_PATTERN = re.compile(r'\b([A-Z][a-zA-Z]+Exception|Error)\s*[:\s]+([A-Z]?\d{3,6})\b', re.IGNORECASE)


def _extract_timestamp(line: str) -> Optional[datetime]:
    """Extract timestamp from a log line."""
    try:
        from dateutil import parser
        date_patterns = [
            r'\d{4}[-/]\d{2}[-/]\d{2}',
            r'\d{2}[-/]\d{2}[-/]\d{4}',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*',
            r'\b\d{10,13}\b',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                start_idx = max(0, match.start() - 30)
                end_idx = min(len(line), match.end() + 50)
                context = line[start_idx:end_idx]
                
                try:
                    parsed = parser.parse(context, fuzzy=True, default=datetime(1970, 1, 1))
                    if 1970 < parsed.year < 2100:
                        return parsed
                except (ValueError, parser.ParserError):
                    continue
    except ImportError:
        pass
    
    iso_patterns = [
        (r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?)', ['%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S']),
        (r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)', ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']),
    ]
    
    for pattern, formats in iso_patterns:
        match = re.search(pattern, line)
        if match:
            timestamp_str = match.group(1)
            clean_str = re.sub(r'[+-]\d{2}:?\d{2}|Z', '', timestamp_str)
            for fmt in formats:
                try:
                    if '.%f' in fmt and '.' not in clean_str:
                        continue
                    return datetime.strptime(clean_str[:26], fmt)
                except ValueError:
                    continue
    
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    
    return None


def _extract_log_level(line: str) -> Optional[str]:
    """Extract log level from a log line."""
    bracket_pattern = r'\[(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\]'
    match = re.search(bracket_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    colon_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE):\s*'
    match = re.search(colon_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    timestamp_log_pattern = r'(?:\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}.*?)\s+(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    match = re.search(timestamp_log_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None


def _extract_error_codes_from_line(line: str) -> List[Tuple[str, str]]:
    """
    Extract all error codes from a single line using multiple patterns.
    
    Returns:
        List of tuples: (code, pattern_type) where pattern_type indicates which pattern matched
    """
    codes = []
    seen = set()
    
    # Pattern 1: HTTP status codes (e.g., 404, 500, 503)
    # Only match if it's clearly an HTTP status (has "HTTP" or "Status" nearby, or is in error context)
    for match in HTTP_STATUS_PATTERN.finditer(line):
        code = match.group(1)
        
        # Skip if it looks like milliseconds in a timestamp (e.g., .567 or .345)
        if match.start() > 0 and line[match.start() - 1] == '.':
            # Check if there's a time pattern before it (HH:MM:SS)
            before_context = line[max(0, match.start() - 15):match.start()]
            if re.search(r'\d{2}:\d{2}:\d{2}', before_context):
                continue  # This is likely milliseconds, skip it
        
        # Additional validation: check context around the match
        start = max(0, match.start() - 20)
        end = min(len(line), match.end() + 20)
        context = line[start:end].lower()
        
        # Only accept if it's clearly an HTTP status or in an error context
        # But require stronger evidence (HTTP/Status keywords) for 3-digit codes
        is_http_status = 'http' in context or 'status' in context
        is_error_context = 'error' in context or 'code' in context or 'failed' in context or 'exception' in context
        
        if code not in seen:
            # For 3-digit codes, require HTTP/Status keyword unless it's clearly in error context
            if is_http_status or (is_error_context and not _looks_like_timestamp(code, line, match.start())):
                codes.append((code, 'HTTP_STATUS'))
                seen.add(code)
    
    # Pattern 2: Standard error codes (e.g., ERR001, DB1001E)
    for match in STANDARD_ERROR_PATTERN.finditer(line):
        code = match.group(1)
        if code not in seen:
            codes.append((code, 'STANDARD'))
            seen.add(code)
    
    # Pattern 3: Numeric error codes with prefix (e.g., error: 1001, code: 500)
    for match in NUMERIC_ERROR_PATTERN.finditer(line):
        code = match.group(1)
        # Validate: should be 3-6 digits, and not look like a timestamp
        if code not in seen and len(code) >= 3 and not _looks_like_timestamp(code, line, match.start()):
            codes.append((code, 'NUMERIC'))
            seen.add(code)
    
    # Pattern 4: Custom codes with separators (e.g., ERROR_500, DB-1001, AUTH_ERR_001)
    for match in CUSTOM_CODE_PATTERN.finditer(line):
        code = match.group(1)
        # Filter out common false positives
        if code not in seen and not any(x in code.upper() for x in ['HTTP', 'STATUS']):
            # Check if it looks like an error code (has numbers and letters)
            if re.search(r'\d', code) and re.search(r'[A-Z]', code.upper()):
                codes.append((code, 'CUSTOM'))
                seen.add(code)
    
    # Pattern 5: Hexadecimal codes (e.g., 0x80004005)
    for match in HEX_CODE_PATTERN.finditer(line):
        code = match.group(1).upper()
        if code not in seen:
            codes.append((code, 'HEX'))
            seen.add(code)
    
    # Pattern 6: Exception with error code (e.g., DatabaseException: 1001)
    for match in EXCEPTION_CODE_PATTERN.finditer(line):
        code = match.group(2)
        if code not in seen:
            codes.append((code, 'EXCEPTION_CODE'))
            seen.add(code)
    
    return codes


def _looks_like_timestamp(code: str, line: str, position: int) -> bool:
    """Check if a numeric code looks like it's part of a timestamp."""
    # Check context around the code
    start = max(0, position - 10)
    end = min(len(line), position + len(code) + 10)
    context = line[start:end]
    
    # Common timestamp patterns that might be mistaken for error codes
    timestamp_indicators = [
        r'\d{2}:\d{2}:\d{2}',  # Time format
        r'\d{4}-\d{2}-\d{2}',  # Date format
        r'\d{2}/\d{2}/\d{4}',  # Date format
        r'\.\d{3,6}',  # Milliseconds/microseconds
    ]
    
    for pattern in timestamp_indicators:
        if re.search(pattern, context):
            return True
    
    return False


def search_by_error_code(
    log_content: Union[str, List[str]],
    error_codes: Union[str, List[str]],
    case_sensitive: bool = False
) -> List[str]:
    """
    Search log content for lines containing specific error code(s).
    
    Args:
        log_content: Log file path, log content as string, or list of log lines.
        error_codes: Single error code string or list of error codes to search for.
        case_sensitive: Whether the search should be case-sensitive.
    
    Returns:
        List of matching log lines.
    """
    # Normalize error codes to list
    if isinstance(error_codes, str):
        error_codes_list = [error_codes]
    else:
        error_codes_list = [str(code) for code in error_codes]
    
    # Normalize codes based on case sensitivity
    if not case_sensitive:
        error_codes_list = [code.upper() for code in error_codes_list]
    
    # Handle file path input
    if isinstance(log_content, str) and os.path.isfile(log_content):
        with open(log_content, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    # Handle string content
    elif isinstance(log_content, str):
        lines = log_content.splitlines()
    # Handle list of lines
    else:
        lines = log_content
    
    matched_lines = []
    
    for line in lines:
        # Extract all error codes from this line
        extracted_codes = _extract_error_codes_from_line(line)
        
        # Check if any extracted code matches our search criteria
        for extracted_code, _ in extracted_codes:
            code_to_check = extracted_code if case_sensitive else extracted_code.upper()
            if code_to_check in error_codes_list:
                matched_lines.append(line.rstrip('\n'))
                break  # Found a match, no need to check other codes in this line
    
    return matched_lines


def extract_all_error_codes(
    log_content: Union[str, List[str]]
) -> Tuple[List[ErrorCodeMatch], ErrorCodeSummary]:
    """
    Extract all error codes from log content.
    
    Args:
        log_content: Log file path, log content as string, or list of log lines.
    
    Returns:
        Tuple of (list of ErrorCodeMatch objects, ErrorCodeSummary)
    """
    # Handle file path input
    if isinstance(log_content, str) and os.path.isfile(log_content):
        with open(log_content, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    # Handle string content
    elif isinstance(log_content, str):
        lines = log_content.splitlines()
    # Handle list of lines
    else:
        lines = log_content
    
    matches: List[ErrorCodeMatch] = []
    code_counter = Counter()
    code_types: Dict[str, List[str]] = defaultdict(list)
    code_details: Dict[str, ErrorCodeMatch] = {}
    
    for line_num, line in enumerate(lines, 1):
        # Skip empty lines
        if not line.strip():
            continue
        
        # Extract all error codes from this line
        extracted_codes = _extract_error_codes_from_line(line)
        
        for code, pattern_type in extracted_codes:
            code_counter[code] += 1
            code_types[pattern_type].append(code)
            
            # Create match object
            match = ErrorCodeMatch(
                code=code,
                line_number=line_num,
                line_content=line.rstrip('\n'),
                timestamp=_extract_timestamp(line),
                log_level=_extract_log_level(line),
                context=pattern_type
            )
            
            matches.append(match)
            
            # Store first occurrence details for each unique code
            if code not in code_details:
                code_details[code] = match
    
    summary = ErrorCodeSummary(
        total_matches=len(matches),
        unique_codes=len(code_counter),
        codes_by_frequency=dict(code_counter),
        codes_by_type={k: list(set(v)) for k, v in code_types.items()},
        code_details=code_details
    )
    
    return matches, summary


def search_by_error_code_to_file(
    log_content: Union[str, List[str]],
    error_codes: Union[str, List[str]],
    output_file: Optional[str] = None,
    case_sensitive: bool = False
) -> str:
    """
    Search log content for specific error code(s) and write results to a file.
    
    Args:
        log_content: Log file path, log content as string, or list of log lines.
        error_codes: Single error code string or list of error codes to search for.
        output_file: Path to output file. If None, creates a temporary file.
        case_sensitive: Whether the search should be case-sensitive.
    
    Returns:
        Path to the output file containing matching log lines.
    """
    matched_lines = search_by_error_code(log_content, error_codes, case_sensitive)
    
    # Write to file
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(matched_lines))
            if matched_lines:
                f.write('\n')
        return output_file
    else:
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
        temp_file.write('\n'.join(matched_lines))
        temp_file.close()
        return temp_file.name


def format_error_code_summary(summary: ErrorCodeSummary) -> str:
    """Format error code summary as a readable string."""
    output = []
    output.append("=" * 80)
    output.append("ERROR CODE EXTRACTION SUMMARY")
    output.append("=" * 80)
    output.append("")
    
    output.append(f"Total Error Code Matches: {summary.total_matches}")
    output.append(f"Unique Error Codes Found: {summary.unique_codes}")
    output.append("")
    
    if summary.codes_by_frequency:
        output.append("Error Codes by Frequency:")
        output.append("-" * 80)
        sorted_codes = sorted(
            summary.codes_by_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )
        for code, count in sorted_codes:
            code_type = summary.code_details.get(code, ErrorCodeMatch(code=code, line_number=0, line_content="")).context
            output.append(f"  {code:20s} : {count:>5d} occurrence(s) [{code_type}]")
        output.append("")
    
    if summary.codes_by_type:
        output.append("Error Codes by Type:")
        output.append("-" * 80)
        for code_type, codes in sorted(summary.codes_by_type.items()):
            unique_codes = list(set(codes))
            output.append(f"  {code_type:20s} : {len(unique_codes)} unique code(s)")
            if len(unique_codes) <= 10:
                output.append(f"    {', '.join(unique_codes)}")
        output.append("")
    
    if summary.code_details:
        output.append("Sample Occurrences (First occurrence of each code):")
        output.append("-" * 80)
        for code, match in list(summary.code_details.items())[:10]:  # Show first 10
            output.append(f"  Code: {code} [{match.context}]")
            output.append(f"    Line {match.line_number}: {match.line_content[:70]}...")
            if match.timestamp:
                output.append(f"    Timestamp: {match.timestamp}")
            output.append("")
    
    output.append("=" * 80)
    
    return "\n".join(output)


def interactive_search_by_error_code(
    log_file: str,
    error_codes: Union[str, List[str], None] = None
) -> List[str]:
    """
    Interactive function to search log file by error code(s).
    Creates output file with matching lines in the output folder.
    
    Args:
        log_file: Path to the log file to process.
        error_codes: Optional error code(s). If provided, uses these.
                    If None, prompts user interactively.
    
    Returns:
        List of output file paths created.
    """
    # Validate input file
    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Log file not found: {log_file}")
    
    # Find project root
    abs_log_file = os.path.abspath(log_file)
    current_dir = os.path.dirname(abs_log_file)
    
    base_dir = current_dir
    while base_dir != os.path.dirname(base_dir):
        if os.path.isdir(os.path.join(base_dir, 'utilities')) and \
           (os.path.isdir(os.path.join(base_dir, 'tests')) or 
            os.path.isdir(os.path.join(base_dir, 'agent'))):
            break
        base_dir = os.path.dirname(base_dir)
    
    if not base_dir or base_dir == os.path.dirname(base_dir):
        base_dir = os.getcwd()
    
    # Create output directory
    output_dir = os.path.join(base_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # Extract filename without extension
    file_basename = os.path.basename(log_file)
    file_name_without_ext = os.path.splitext(file_basename)[0]
    
    # First, extract all error codes to show user what's available
    print("\n" + "=" * 60)
    print("ERROR CODE SEARCH - Interactive Mode")
    print("=" * 60)
    print(f"\nProcessing file: {log_file}")
    print("\nScanning for error codes...")
    
    _, summary = extract_all_error_codes(log_file)
    
    if summary.unique_codes == 0:
        print("\n⚠ No error codes found in the log file.")
        print("You can still search for specific codes manually.")
    else:
        print(f"\n✓ Found {summary.unique_codes} unique error code(s) in the log file.")
        print("\nAvailable error codes (top 20):")
        sorted_codes = sorted(
            summary.codes_by_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )[:20]
        for idx, (code, count) in enumerate(sorted_codes, 1):
            print(f"  {idx:2d}. {code:20s} ({count} occurrence(s))")
    
    # Parse error codes - either from parameter or user input
    selected_codes = []
    
    if error_codes is not None:
        # Use provided error codes
        if isinstance(error_codes, str):
            parts = re.split(r'[,;\s]+', error_codes)
            selected_codes = [part.strip() for part in parts if part.strip()]
        else:
            selected_codes = [str(code).strip() for code in error_codes]
    else:
        # Prompt user
        print("\n" + "-" * 60)
        print("Enter error code(s) to search for:")
        print("  - Comma-separated or space-separated: 503, 404, ERR001")
        print("  - Or enter numbers from the list above: 1,2,3")
        print("  - Type 'all' to extract all error codes")
        print("  - Type 'summary' to see detailed summary")
        print("  - Type 'quit' to exit")
        
        user_input = input("\nYour selection: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Exiting...")
            return []
        
        if user_input.lower() == 'all':
            selected_codes = list(summary.codes_by_frequency.keys())
        elif user_input.lower() == 'summary':
            print("\n" + format_error_code_summary(summary))
            return []
        else:
            # Parse user input
            parts = re.split(r'[,;\s]+', user_input)
            sorted_codes_list = sorted(
                summary.codes_by_frequency.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                
                # Check if it's a number (index from the list)
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(sorted_codes_list):
                        selected_codes.append(sorted_codes_list[idx][0])
                else:
                    # Treat as error code
                    selected_codes.append(part)
    
    if not selected_codes:
        print("No error codes selected. Exiting...")
        return []
    
    # Remove duplicates while preserving order
    seen = set()
    selected_codes = [x for x in selected_codes if not (x in seen or seen.add(x))]
    
    print(f"\nSelected error code(s): {', '.join(selected_codes)}")
    print(f"Output directory: {output_dir}")
    print("\nProcessing...")
    
    # Search for each error code
    all_matched_lines = search_by_error_code(log_file, selected_codes, case_sensitive=False)
    
    if not all_matched_lines:
        print(f"\n⚠ No matches found for error code(s): {', '.join(selected_codes)}")
        return []
    
    # Create output filename
    codes_str = "_".join(selected_codes[:3])  # Use first 3 codes for filename
    if len(selected_codes) > 3:
        codes_str += f"_and_{len(selected_codes) - 3}_more"
    output_filename = f"{file_name_without_ext}_error_code_{codes_str}.log"
    output_path = os.path.join(output_dir, output_filename)
    
    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_matched_lines))
        if all_matched_lines:
            f.write('\n')
    
    print(f"  ✓ Created {output_filename} ({len(all_matched_lines)} lines)")
    print(f"\n✓ Successfully created output file: {output_path}")
    
    return [output_path]


def main():
    """
    Main entry point for running the error code search from command line.
    Usage: python error_code.py [log_file_path] [error_codes] [--extract-all] [--summary]
    
    Examples:
        python error_code.py utilities/data.log 503 404
        python error_code.py utilities/data.log "503, 404, ERR001"
        python error_code.py utilities/data.log --extract-all
        python error_code.py utilities/data.log --summary
    """
    import sys
    
    log_file = None
    error_codes = None
    extract_all = False
    show_summary = False
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        log_file = sys.argv[1]
        
        # Check for flags
        if '--extract-all' in sys.argv:
            extract_all = True
        if '--summary' in sys.argv:
            show_summary = True
        
        # Get error codes from remaining arguments (excluding flags)
        code_args = [arg for arg in sys.argv[2:] if not arg.startswith('--')]
        if code_args:
            error_codes = ' '.join(code_args)
    
    if log_file is None:
        # Prompt user for file path
        print("\n" + "=" * 60)
        print("ERROR CODE SEARCH - File Input")
        print("=" * 60)
        print("\nEnter the path to the log file you want to search:")
        print("Example: utilities/data.log")
        print("         or: /full/path/to/your/logfile.log")
        print("Type 'quit' to exit")
        
        while True:
            user_file_input = input("\nLog file path: ").strip()
            
            if user_file_input.lower() in ['quit', 'exit', 'q']:
                print("Exiting...")
                sys.exit(0)
            
            if not user_file_input:
                print("Please enter a file path.")
                continue
            
            # Check if file exists
            if os.path.isfile(user_file_input):
                log_file = user_file_input
                break
            else:
                # Try relative paths
                script_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(script_dir)
                possible_paths = [
                    user_file_input,
                    os.path.join(parent_dir, user_file_input),
                    os.path.join(script_dir, user_file_input),
                    os.path.join(os.getcwd(), user_file_input)
                ]
                
                found = False
                for path in possible_paths:
                    if os.path.isfile(path):
                        log_file = path
                        found = True
                        break
                
                if found:
                    break
                else:
                    print(f"Error: File not found: {user_file_input}")
                    print("Please check the path and try again, or type 'quit' to exit.")
    
    try:
        if show_summary:
            # Show summary only
            _, summary = extract_all_error_codes(log_file)
            print("\n" + format_error_code_summary(summary))
        elif extract_all:
            # Extract all error codes
            output_files = interactive_search_by_error_code(log_file, error_codes='all')
            if output_files:
                print("\n✓ Processing complete!")
        else:
            # Search for specific error codes
            output_files = interactive_search_by_error_code(log_file, error_codes)
            if output_files:
                print("\n✓ Processing complete!")
            else:
                print("\nNo files were created.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_error_code_search(
    file_path: str,
    error_codes: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True,
    case_sensitive: bool = False
) -> Dict:
    """
    Core function to search log file by error code(s).
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        error_codes: Single error code string or list of error codes
        output_dir: Directory to write output file (default: "output")
        write_file: Whether to write output file (default: True)
        case_sensitive: Whether search should be case-sensitive (default: False)
    
    Returns:
        Dictionary with:
        - success: bool
        - matched_lines: List[str]
        - output_file: str | None
        - codes_found: List[str]
        - counts_by_code: Dict[str, int]
        - error: str | None
    """
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return {
                "success": False,
                "matched_lines": [],
                "output_file": None,
                "codes_found": [],
                "counts_by_code": {},
                "error": f"File not found: {file_path}"
            }
        
        # Normalize error codes to list
        if isinstance(error_codes, str):
            error_codes_list = [error_codes]
        else:
            error_codes_list = [str(code) for code in error_codes]
        
        if not error_codes_list:
            return {
                "success": False,
                "matched_lines": [],
                "output_file": None,
                "codes_found": [],
                "counts_by_code": {},
                "error": "No error codes provided"
            }
        
        # Search for error codes
        matched_lines = search_by_error_code(file_path, error_codes_list, case_sensitive)
        
        # Count occurrences by code - extract codes from matched lines
        counts_by_code = {}
        codes_found = set()
        
        # Extract all codes from the file to get accurate counts
        all_matches, all_summary = extract_all_error_codes(file_path)
        
        # Count occurrences of requested codes
        for match in all_matches:
            code = match.code if case_sensitive else match.code.upper()
            code_to_check = code if case_sensitive else code.upper()
            normalized_requested = [c.upper() if not case_sensitive else c for c in error_codes_list]
            
            if code_to_check in normalized_requested or code in error_codes_list:
                codes_found.add(code)
                counts_by_code[code] = counts_by_code.get(code, 0) + 1
        
        codes_found = list(codes_found)
        
        output_file = None
        if write_file and matched_lines:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            file_basename = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            codes_str = "_".join(error_codes_list[:3])
            if len(error_codes_list) > 3:
                codes_str += f"_and_{len(error_codes_list) - 3}_more"
            output_filename = f"{file_name_without_ext}_error_code_{codes_str}.log"
            output_file = os.path.join(output_dir, output_filename)
            
            # Write to file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(matched_lines))
                if matched_lines:
                    f.write('\n')
        
        return {
            "success": True,
            "matched_lines": matched_lines,
            "output_file": output_file,
            "codes_found": codes_found,
            "counts_by_code": counts_by_code,
            "error": None
        }
    
    except Exception as e:
        return {
            "success": False,
            "matched_lines": [],
            "output_file": None,
            "codes_found": [],
            "counts_by_code": {},
            "error": str(e)
        }


def run_error_code_extract_all(
    file_path: str,
    output_dir: str = "output",
    write_summary: bool = True
) -> Dict:
    """
    Core function to extract all error codes from log file.
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        output_dir: Directory to write summary file (default: "output")
        write_summary: Whether to write summary file (default: True)
    
    Returns:
        Dictionary with:
        - success: bool
        - matches: List[ErrorCodeMatch]
        - summary: ErrorCodeSummary
        - summary_file: str | None
        - formatted_summary: str
        - error: str | None
    """
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return {
                "success": False,
                "matches": [],
                "summary": None,
                "summary_file": None,
                "formatted_summary": "",
                "error": f"File not found: {file_path}"
            }
        
        # Extract all error codes
        matches, summary = extract_all_error_codes(file_path)
        
        # Format summary
        formatted_summary = format_error_code_summary(summary)
        
        summary_file = None
        if write_summary:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            file_basename = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            summary_filename = f"{file_name_without_ext}_error_code_summary.txt"
            summary_file = os.path.join(output_dir, summary_filename)
            
            # Write summary to file
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(formatted_summary)
        
        return {
            "success": True,
            "matches": matches,
            "summary": summary,
            "summary_file": summary_file,
            "formatted_summary": formatted_summary,
            "error": None
        }
    
    except Exception as e:
        return {
            "success": False,
            "matches": [],
            "summary": None,
            "summary_file": None,
            "formatted_summary": "",
            "error": str(e)
        }


if __name__ == "__main__":
    main()
