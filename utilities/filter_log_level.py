import re
import os
import tempfile
from typing import Union, List


def filter_by_log_level(log_content: Union[str, List[str]], log_levels: Union[str, List[str]]) -> List[str]:
    
    # Normalize log_levels to list
    if isinstance(log_levels, str):
        log_levels = [log_levels]
    else:
        log_levels = [str(level) for level in log_levels]
    
    # Normalize to uppercase for matching
    log_levels_normalized = [level.upper() for level in log_levels]
    
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
        
        # Extract log level from the line
        log_level = _extract_log_level(line)
        
        if log_level is None:
            continue
        
        # Check if log level matches any of the requested levels
        if log_level.upper() in log_levels_normalized:
            filtered_lines.append(line.rstrip('\n'))
    
    return filtered_lines


def _extract_log_level(line: str) -> Union[str, None]:
    """
    Extract log level from a log line. Supports various log level formats.
    
    Common formats supported:
    - ERROR, ERR, FATAL, CRITICAL
    - WARN, WARNING
    - INFO
    - DEBUG
    - TRACE
    - Custom levels
    
    Args:
        line (str): A log line.
    
    Returns:
        str or None: Extracted log level if found, None otherwise.
    """
    # Common log level patterns (case-insensitive)
    # Pattern 1: [ERROR], [INFO], etc. (brackets)
    bracket_pattern = r'\[(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\]'
    match = re.search(bracket_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 2: ERROR:, INFO:, etc. (with colon)
    colon_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE):\s*'
    match = re.search(colon_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 3: ERROR , INFO , etc. (with space)
    space_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s+'
    match = re.search(space_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 4: ERROR - INFO - etc. (with dash)
    dash_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s*-\s*'
    match = re.search(dash_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 5: Standard log4j/slf4j format: ERROR  or INFO  (multiple spaces)
    log4j_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s{2,}'
    match = re.search(log4j_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 6: Uppercase at start of line or after timestamp
    # After timestamp formats like: 2024-01-01 10:00:00 ERROR message
    timestamp_log_pattern = r'(?:\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}.*?)\s+(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    match = re.search(timestamp_log_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 7: Simple word boundary match (last resort)
    simple_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    matches = re.findall(simple_pattern, line, re.IGNORECASE)
    if matches:
        # Return the first match, preferring more specific levels
        for level in ['ERROR', 'FATAL', 'CRITICAL', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']:
            if level in [m.upper() for m in matches]:
                return level
    
    return None


def filter_by_log_level_to_file(log_content: Union[str, List[str]], log_levels: Union[str, List[str]], output_file: Union[str, None] = None) -> str:
    """
    Filter log lines by log level(s) and write them to a file.
    
    Args:
        log_content (str or list of str): The log file path, log content as string, or list of log lines.
        log_levels (str or list of str): Log level(s) to filter by (case-insensitive).
        output_file (str, optional): Path to output file. If None, creates a temporary file.
    
    Returns:
        str: Path to the output file containing the filtered log lines.
    """
    # Get filtered lines
    filtered_lines = filter_by_log_level(log_content, log_levels)
    
    # Write to file
    if output_file:
        # Write to specified file
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(filtered_lines))
        return output_file
    else:
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
        temp_file.write('\n'.join(filtered_lines))
        temp_file.close()
        return temp_file.name

