import re
from datetime import datetime
from typing import Union, List, Dict, Optional
import os


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
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return {
                "success": False,
                "lines_found": 0,
                "output_file": None,
                "sample_lines": [],
                "time_range": {},
                "error": f"File not found: {file_path}"
            }
        
        if start_time >= end_time:
            return {
                "success": False,
                "lines_found": 0,
                "output_file": None,
                "sample_lines": [],
                "time_range": {},
                "error": "Start time must be before end time"
            }
        
        # Filter lines by time range
        filtered_lines = slice_by_time(file_path, start_time, end_time)
        
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
        
        # Get sample lines (first 10)
        sample_lines = filtered_lines[:10]
        
        return {
            "success": True,
            "lines_found": len(filtered_lines),
            "output_file": output_file,
            "sample_lines": sample_lines,
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            "error": None
        }
    
    except Exception as e:
        return {
            "success": False,
            "lines_found": 0,
            "output_file": None,
            "sample_lines": [],
            "time_range": {},
            "error": str(e)
        }
