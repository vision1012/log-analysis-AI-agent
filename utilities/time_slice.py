import re
from datetime import datetime
from typing import Union, List, Dict, Optional
import os
import tempfile

try:
    from .tool_result import create_tool_result, format_datetime_for_summary
except ImportError:
    from tool_result import create_tool_result, format_datetime_for_summary


def _find_project_root(start_path: str = None) -> str:
    """Find the project root directory."""
    if start_path is None:
        start_path = os.getcwd()
    
    current_dir = os.path.abspath(start_path)
    if os.path.isfile(current_dir):
        current_dir = os.path.dirname(current_dir)
    
    base_dir = current_dir
    while base_dir != os.path.dirname(base_dir):
        if os.path.isdir(os.path.join(base_dir, 'utilities')) and \
           (os.path.isdir(os.path.join(base_dir, 'tests')) or 
            os.path.isdir(os.path.join(base_dir, 'agent'))):
            return base_dir
        base_dir = os.path.dirname(base_dir)
    
    return os.getcwd()


def slice_by_time(log_content: Union[str, List[str]], start_time: datetime, end_time: datetime) -> List[str]:
    
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
    
    filtered_lines = []
    
    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue
            
        # Extract timestamp from the line
        timestamp = _extract_timestamp(line)
        
        if timestamp is None:
            continue
        
        # Normalize timestamp to timezone-naive for comparison
        # If timestamp is timezone-aware, convert to naive by replacing tzinfo
        if timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)
        
        # Check if timestamp is within range
        if start_time <= timestamp <= end_time:
            filtered_lines.append(line.rstrip('\n'))
    
    return filtered_lines


def _extract_timestamp(line: str) -> Union[datetime, None]:
    
    # Try parsing with dateutil if available (handles most formats automatically)
    try:
        from dateutil import parser
        # Try to find any date-like pattern in the line
        date_patterns = [
            r'\d{4}[-/]\d{2}[-/]\d{2}',  # YYYY-MM-DD or YYYY/MM/DD
            r'\d{2}[-/]\d{2}[-/]\d{4}',  # MM-DD-YYYY or DD-MM-YYYY
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*',  # Month names
            r'\b\d{10,13}\b',  # Unix timestamps
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # Try to extract a larger context around the match
                start_idx = max(0, match.start() - 30)
                end_idx = min(len(line), match.end() + 50)
                context = line[start_idx:end_idx]
                
                try:
                    # dateutil can parse many formats automatically
                    parsed = parser.parse(context, fuzzy=True, default=datetime(1970, 1, 1))
                    # Normalize to timezone-naive
                    if parsed.tzinfo is not None:
                        parsed = parsed.replace(tzinfo=None)
                    if parsed.year > 1970 and parsed.year < 2100:  # Reasonable year range
                        return parsed
                except (ValueError, parser.ParserError, OverflowError):
                    continue
    except ImportError:
        pass  # Continue with manual parsing
    
    # Manual format parsing (for when dateutil is not available)
    
    # ISO 8601 formats: 2024-01-01T10:00:00 or 2024-01-01 10:00:00
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
                    return datetime.strptime(clean_str[:26], fmt)  # Limit microseconds
                except ValueError:
                    continue
    
    # Syslog format: Jan  1 10:00:00 or Jan 01 10:00:00
    syslog_pattern = r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})'
    match = re.search(syslog_pattern, line)
    if match:
        timestamp_str = match.group(1)
        for fmt in ['%b %d %H:%M:%S', '%b  %d %H:%M:%S']:  # Handle single/double space
            try:
                # Use current year as default
                dt = datetime.strptime(timestamp_str, fmt)
                dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue
    
    # RFC 2822 format: Mon, 01 Jan 2024 10:00:00 +0000
    rfc2822_pattern = r'([A-Z][a-z]{2},\s+\d{2}\s+[A-Z][a-z]{2}\s+\d{4}\s+\d{2}:\d{2}:\d{2}(?:\s+[+-]\d{4})?)'
    match = re.search(rfc2822_pattern, line)
    if match:
        timestamp_str = match.group(1)
        try:
            from email.utils import parsedate_to_datetime
            parsed = parsedate_to_datetime(timestamp_str)
            # Normalize to timezone-naive
            if parsed.tzinfo is not None:
                parsed = parsed.replace(tzinfo=None)
            return parsed
        except (ImportError, ValueError, TypeError):
            # Manual parsing
            clean_str = re.sub(r'\s+[+-]\d{4}', '', timestamp_str)
            try:
                return datetime.strptime(clean_str, '%a, %d %b %Y %H:%M:%S')
            except ValueError:
                pass
    
    # Apache/Nginx common format: [01/Jan/2024:10:00:00 +0000]
    apache_pattern = r'\[(\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}(?:\s+[+-]\d{4})?)\]'
    match = re.search(apache_pattern, line)
    if match:
        timestamp_str = match.group(1)
        clean_str = re.sub(r'\s+[+-]\d{4}', '', timestamp_str)
        try:
            return datetime.strptime(clean_str, '%d/%b/%Y:%H:%M:%S')
        except ValueError:
            pass
    
    # Format: [YYYY-MM-DD HH:MM:SS] or [YYYY-MM-DD HH:MM:SS.mmm]
    bracket_patterns = [
        (r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?)\]', ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S']),
    ]
    for pattern, formats in bracket_patterns:
        match = re.search(pattern, line)
        if match:
            timestamp_str = match.group(1)
            for fmt in formats:
                try:
                    if '.%f' in fmt and '.' not in timestamp_str:
                        continue
                    return datetime.strptime(timestamp_str[:26], fmt)
                except ValueError:
                    continue
    
    # Format: YYYY-MM-DD HH:MM:SS,mmm or YYYY-MM-DD HH:MM:SS.mmm
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,\.]\d+)', line)
    if match:
        timestamp_str = match.group(1)
        base_str = re.sub(r'[.,]\d+', '', timestamp_str)
        try:
            return datetime.strptime(base_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    
    # Unix timestamp (seconds - 10 digits)
    match = re.search(r'\b(1[0-9]{9}|[2-9][0-9]{9})\b', line)
    if match:
        try:
            ts = int(match.group(1))
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            pass
    
    # Unix timestamp (milliseconds - 13 digits)
    match = re.search(r'\b(1[0-9]{12}|[2-9][0-9]{12})\b', line)
    if match:
        try:
            ts_ms = int(match.group(1))
            # Check if it's a reasonable timestamp (not too large)
            if ts_ms > 0 and ts_ms < 9999999999999:  # Reasonable upper bound
                ts = ts_ms / 1000
                return datetime.fromtimestamp(ts)
        except (ValueError, OSError, OverflowError):
            pass
    
    # Format: MM/DD/YYYY HH:MM:SS
    match = re.search(r'(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%m/%d/%Y %H:%M:%S')
        except ValueError:
            pass
    
    # Format: DD-MM-YYYY HH:MM:SS
    match = re.search(r'(\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d-%m-%Y %H:%M:%S')
        except ValueError:
            pass
    
    # Format: YYYY/MM/DD HH:MM:SS
    match = re.search(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y/%m/%d %H:%M:%S')
        except ValueError:
            pass
    
    # Format: HH:MM:SS (time only - use current date)
    match = re.search(r'\b(\d{2}:\d{2}:\d{2})\b', line)
    if match:
        time_str = match.group(1)
        try:
            time_obj = datetime.strptime(time_str, '%H:%M:%S').time()
            return datetime.combine(datetime.now().date(), time_obj)
        except ValueError:
            pass
    
    # 12-hour format: HH:MM:SS AM/PM
    match = re.search(r'(\d{1,2}:\d{2}:\d{2}\s+[AP]M)', line, re.IGNORECASE)
    if match:
        time_str = match.group(1)
        try:
            time_obj = datetime.strptime(time_str, '%I:%M:%S %p').time()
            return datetime.combine(datetime.now().date(), time_obj)
        except ValueError:
            pass
    
    return None


def slice_by_time_range(log_file: str, start_time: datetime, end_time: datetime) -> List[str]:
    
    return slice_by_time(log_file, start_time, end_time)


def run_time_slice(
    file_path: str,
    start_time: datetime,
    end_time: datetime,
    output_dir: str = "output",
    write_file: bool = True
) -> Dict:
    """
    Core function to slice log file by time range.
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        start_time: Start datetime for the time range
        end_time: End datetime for the time range
        output_dir: Directory to write output file (default: "output")
        write_file: Whether to write output file (default: True)
    
    Returns:
        Dictionary with:
        - success: bool
        - lines_found: int
        - output_file: str | None
        - sample_lines: List[str] (first 10 lines)
        - time_range: dict with start/end timestamps
        - error: str | None
    """
    input_params = {
        "file_path": file_path,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "options": {
            "output_dir": output_dir,
            "write_file": write_file
        }
    }
    
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_time_slice",
                status="error",
                input_params=input_params,
                errors=[f"File not found: {file_path}"]
            )
        
        if start_time >= end_time:
            return create_tool_result(
                tool="run_time_slice",
                status="error",
                input_params=input_params,
                errors=["Start time must be before end time"]
            )
        
        # Filter lines by time range
        filtered_lines = slice_by_time(file_path, start_time, end_time)
        
        artifacts = []
        output_file = None
        if write_file and filtered_lines:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            file_basename = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            start_str = start_time.strftime('%Y%m%d_%H%M%S')
            end_str = end_time.strftime('%Y%m%d_%H%M%S')
            output_filename = f"{file_name_without_ext}_time_{start_str}_to_{end_str}.log"
            output_file = os.path.join(output_dir, output_filename)
            
            # Write to file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(filtered_lines))
                f.write('\n')
            
            artifacts.append({
                "type": "file",
                "name": output_filename,
                "path": output_file
            })
        
        # Get sample lines (first 10)
        sample_lines = filtered_lines[:10]
        
        # Create summary
        time_range_str = f"{format_datetime_for_summary(start_time)} → {format_datetime_for_summary(end_time)}"
        summary = {
            "headline": f"Time slice: {len(filtered_lines)} lines found",
            "key_metrics": {
                "lines_found": len(filtered_lines),
                "time_range": time_range_str,
                "sample_lines_count": len(sample_lines)
            }
        }
        
        # Create data payload
        data = {
            "items": sample_lines,
            "text": f"Found {len(filtered_lines)} log lines in time range {time_range_str}",
            "json": {
                "all_lines_count": len(filtered_lines),
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat()
                },
                "sample_lines": sample_lines
            }
        }
        
        return create_tool_result(
            tool="run_time_slice",
            status="success",
            input_params=input_params,
            summary=summary,
            data=data,
            artifacts=artifacts
        )
    
    except Exception as e:
        return create_tool_result(
            tool="run_time_slice",
            status="error",
            input_params=input_params,
            errors=[str(e)]
        )


def slice_by_time_to_file(
    log_content: Union[str, List[str]],
    start_time: datetime,
    end_time: datetime,
    output_file: Optional[str] = None
) -> str:
    """
    Slice log content by time range and write results to a file.
    
    Args:
        log_content: Log file path, log content as string, or list of log lines.
        start_time: Start datetime for the time range.
        end_time: End datetime for the time range.
        output_file: Path to output file. If None, creates a file in output directory.
    
    Returns:
        Path to the output file containing filtered log lines.
    """
    filtered_lines = slice_by_time(log_content, start_time, end_time)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(filtered_lines))
            if filtered_lines:
                f.write('\n')
        return output_file
    else:
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
        temp_file.write('\n'.join(filtered_lines))
        if filtered_lines:
            temp_file.write('\n')
        temp_file.close()
        return temp_file.name


def interactive_slice_by_time(
    log_file: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> str:
    """
    Interactive function to slice log file by time range.
    Creates output file with matching lines in the output folder.
    
    Args:
        log_file: Path to the log file to process.
        start_time: Optional start datetime. If None, prompts user interactively.
        end_time: Optional end datetime. If None, prompts user interactively.
    
    Returns:
        Path to the output file created.
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
    
    print("\n" + "=" * 60)
    print("TIME SLICE - Interactive Mode")
    print("=" * 60)
    print(f"\nProcessing file: {log_file}")
    
    # Get time range from user if not provided
    if start_time is None:
        print("\nEnter start time for the time range:")
        print("Format: YYYY-MM-DD HH:MM:SS")
        print("Example: 2024-01-15 10:30:00")
        print("Type 'quit' to exit")
        
        while True:
            start_str = input("\nStart time: ").strip()
            
            if start_str.lower() in ['quit', 'exit', 'q']:
                print("Exiting...")
                return ""
            
            try:
                start_time = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
                break
            except ValueError:
                print("Error: Invalid format. Please use YYYY-MM-DD HH:MM:SS")
                print("Example: 2024-01-15 10:30:00")
    
    if end_time is None:
        print("\nEnter end time for the time range:")
        print("Format: YYYY-MM-DD HH:MM:SS")
        print("Example: 2024-01-15 12:30:00")
        print("Type 'quit' to exit")
        
        while True:
            end_str = input("\nEnd time: ").strip()
            
            if end_str.lower() in ['quit', 'exit', 'q']:
                print("Exiting...")
                return ""
            
            try:
                end_time = datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
                break
            except ValueError:
                print("Error: Invalid format. Please use YYYY-MM-DD HH:MM:SS")
                print("Example: 2024-01-15 12:30:00")
    
    # Validate time range
    if start_time >= end_time:
        raise ValueError("Start time must be before end time")
    
    print(f"\nTime range: {start_time.strftime('%Y-%m-%d %H:%M:%S')} to {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Output directory: {output_dir}")
    print("\nProcessing...")
    
    # Filter lines by time range
    filtered_lines = slice_by_time(log_file, start_time, end_time)
    
    if not filtered_lines:
        print(f"\n⚠ No log lines found in the specified time range.")
        return ""
    
    # Create output filename
    start_str = start_time.strftime('%Y%m%d_%H%M%S')
    end_str = end_time.strftime('%Y%m%d_%H%M%S')
    output_filename = f"{file_name_without_ext}_time_{start_str}_to_{end_str}.log"
    output_path = os.path.join(output_dir, output_filename)
    
    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(filtered_lines))
        f.write('\n')
    
    print(f"  ✓ Created {output_filename} ({len(filtered_lines)} lines)")
    print(f"\n✓ Successfully created output file: {output_path}")
    
    return output_path


def main():
    """
    Main entry point for running the time slice from command line.
    Usage: python time_slice.py [log_file_path] [start_time] [end_time]
    
    Examples:
        python time_slice.py data/sample.log "2024-01-15 10:00:00" "2024-01-15 12:00:00"
        python time_slice.py data/sample.log
    """
    import sys
    
    log_file = None
    start_time = None
    end_time = None
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        log_file = sys.argv[1]
        
        if len(sys.argv) >= 4:
            try:
                start_time = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M:%S')
                end_time = datetime.strptime(sys.argv[3], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                print("Error: Invalid time format. Use YYYY-MM-DD HH:MM:SS")
                sys.exit(1)
    
    if log_file is None:
        # Prompt user for file path
        print("\n" + "=" * 60)
        print("TIME SLICE - File Input")
        print("=" * 60)
        print("\nEnter the path to the log file you want to slice:")
        print("Example: data/sample.log")
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
        output_file = interactive_slice_by_time(log_file, start_time, end_time)
        if output_file:
            print("\n✓ Processing complete!")
        else:
            print("\nNo file was created.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
