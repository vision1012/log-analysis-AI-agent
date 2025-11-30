import re
from datetime import datetime
from typing import Union, List
import os


def slice_by_time(log_content: Union[str, List[str]], start_time: datetime, end_time: datetime) -> List[str]:
    """
    Extract log lines that fall within the specified time range.
    
    Args:
        log_content (str or list of str): The log file path, log content as string, or list of log lines.
        start_time (datetime): Start time for filtering (inclusive).
        end_time (datetime): End time for filtering (inclusive).
    
    Returns:
        list of str: Log lines that fall within the time range.
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
    
    filtered_lines = []
    
    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue
            
        # Extract timestamp from the line
        timestamp = _extract_timestamp(line)
        
        if timestamp is None:
            continue
        
        # Convert timezone-aware timestamps to naive for comparison
        if timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)
        
        # Check if timestamp is within range
        if start_time <= timestamp <= end_time:
            filtered_lines.append(line.rstrip('\n'))
    
    return filtered_lines


def _extract_timestamp(line: str) -> Union[datetime, None]:
    """
    Extract timestamp from a log line. Supports various common timestamp formats including:
    - ISO 8601 formats (with/without timezone, with/without microseconds)
    - Unix timestamps (seconds and milliseconds)
    - Common log formats (Apache, Nginx, syslog)
    - RFC 3339, RFC 2822 formats
    - Various date formats (US, European, etc.)
    - 12-hour format with AM/PM
    
    Args:
        line (str): A log line.
    
    Returns:
        datetime or None: Parsed timestamp if found, None otherwise.
    """
    # Unix timestamp (milliseconds - 13 digits)
    match = re.search(r'\b(1[0-9]{12}|[2-9][0-9]{12})\b', line)
    if match:
        try:
            ts = int(match.group(1)) / 1000
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            pass
    
    # Unix timestamp (seconds - 10 digits)
    match = re.search(r'\b(1[0-9]{9}|[2-9][0-9]{9})\b', line)
    if match:
        try:
            ts = int(match.group(1))
            return datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            pass
    
    # Manual format parsing
    
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
            return parsedate_to_datetime(timestamp_str)
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
    """
    Convenience function to slice logs from a file by time range.
    
    Args:
        log_file (str): Path to the log file.
        start_time (datetime): Start time for filtering (inclusive).
        end_time (datetime): End time for filtering (inclusive).
    
    Returns:
        list of str: Log lines that fall within the time range.
    """
    return slice_by_time(log_file, start_time, end_time)
