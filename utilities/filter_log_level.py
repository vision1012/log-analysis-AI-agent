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


def interactive_filter_by_log_level(log_file: str, log_levels: Union[str, List[str], None] = None) -> List[str]:
    """
    Interactive function to filter log file by user-selected log levels.
    Creates separate output files for each log level in the output folder.
    
    Args:
        log_file (str): Path to the log file to process.
        log_levels (str, list, or None): Optional log levels. If provided, uses these.
                                        If None, prompts user interactively.
    
    Returns:
        list of str: List of output file paths created.
    
    Example:
        If processing 'data.log' and user selects 'FATAL', creates 'output/data_FATAL.log'
    """
    # Validate input file
    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Log file not found: {log_file}")
    
    # Get base directory (log-analysis-AI-agent directory)
    # Try to find the project root by looking for common markers
    abs_log_file = os.path.abspath(log_file)
    current_dir = os.path.dirname(abs_log_file)
    
    # Look for project root (directory containing utilities/, tests/, etc.)
    base_dir = current_dir
    while base_dir != os.path.dirname(base_dir):  # Stop at filesystem root
        if os.path.isdir(os.path.join(base_dir, 'utilities')) and \
           (os.path.isdir(os.path.join(base_dir, 'tests')) or 
            os.path.isdir(os.path.join(base_dir, 'agent'))):
            break
        base_dir = os.path.dirname(base_dir)
    
    # Fallback to current working directory if not found
    if not base_dir or base_dir == os.path.dirname(base_dir):
        base_dir = os.getcwd()
    
    # Create output directory
    output_dir = os.path.join(base_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # Extract filename without extension
    file_basename = os.path.basename(log_file)
    file_name_without_ext = os.path.splitext(file_basename)[0]
    
    # Available log levels
    available_levels = ['ERROR', 'FATAL', 'CRITICAL', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']
    
    # Parse log levels - either from parameter or user input
    selected_levels = []
    
    if log_levels is not None:
        # Use provided log levels
        if isinstance(log_levels, str):
            # Split if it's a comma/space-separated string
            parts = re.split(r'[,;\s]+', log_levels)
            selected_levels = [part.strip().upper() for part in parts if part.strip()]
        else:
            # It's already a list
            selected_levels = [str(level).strip().upper() for level in log_levels]
        
        # Validate provided levels
        valid_levels = []
        for level in selected_levels:
            if level in available_levels:
                valid_levels.append(level)
            else:
                print(f"Warning: '{level}' is not a valid log level. Skipping...")
        selected_levels = valid_levels
    
    # If no levels provided or all were invalid, prompt user
    if not selected_levels:
        print("\n" + "="*60)
        print("LOG LEVEL FILTER - Interactive Mode")
        print("="*60)
        print(f"\nProcessing file: {log_file}")
        print(f"\nAvailable log levels:")
        for i, level in enumerate(available_levels, 1):
            print(f"  {i}. {level}")
        
        print("\nEnter log levels to filter (comma-separated or space-separated):")
        print("Example: ERROR, FATAL, WARN  or  ERROR FATAL WARN")
        print("Or enter numbers: 1,2,3  or  1 2 3")
        print("Type 'all' to filter all levels")
        print("Type 'quit' to exit")
        
        user_input = input("\nYour selection: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("Exiting...")
            return []
        
        # Parse user input
        if user_input.lower() == 'all':
            selected_levels = available_levels
        else:
            # Split by comma or space
            parts = re.split(r'[,;\s]+', user_input)
            
            for part in parts:
                part = part.strip().upper()
                if not part:
                    continue
                
                # Check if it's a number
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(available_levels):
                        selected_levels.append(available_levels[idx])
                # Check if it's a valid log level
                elif part in available_levels:
                    selected_levels.append(part)
                else:
                    # Try to match partial names
                    matched = [level for level in available_levels if level.startswith(part)]
                    if matched:
                        selected_levels.extend(matched)
                    else:
                        print(f"Warning: '{part}' is not a valid log level. Skipping...")
        
        # Remove duplicates while preserving order
        seen = set()
        selected_levels = [x for x in selected_levels if not (x in seen or seen.add(x))]
    else:
        # Log levels were provided, just show what we're using
        print("\n" + "="*60)
        print("LOG LEVEL FILTER")
        print("="*60)
        print(f"\nProcessing file: {log_file}")
        print(f"Selected log levels: {', '.join(selected_levels)}")
    
    if not selected_levels:
        print("No valid log levels selected. Exiting...")
        return []
    
    if not selected_levels:
        print("No valid log levels selected. Exiting...")
        return []
    
    print(f"\nSelected log levels: {', '.join(selected_levels)}")
    print(f"Output directory: {output_dir}")
    print("\nProcessing...")
    
    # Process each log level and create separate files
    output_files = []
    
    for level in selected_levels:
        # Create output filename: {filename}_{level}.log
        output_filename = f"{file_name_without_ext}_{level}.log"
        output_path = os.path.join(output_dir, output_filename)
        
        # Filter logs for this level
        filtered_lines = filter_by_log_level(log_file, level)
        
        # Write to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(filtered_lines))
        
        output_files.append(output_path)
        print(f"  ✓ Created {output_filename} ({len(filtered_lines)} lines)")
    
    print(f"\n✓ Successfully created {len(output_files)} output file(s) in '{output_dir}'")
    print("\nOutput files:")
    for file_path in output_files:
        print(f"  - {file_path}")
    
    return output_files


def main():
    """
    Main entry point for running the interactive log level filter from command line.
    Usage: python filter_log_level.py [log_file_path] [log_levels]
    
    Examples:
        python filter_log_level.py utilities/data.log
        python filter_log_level.py utilities/data.log ERROR FATAL
        python filter_log_level.py utilities/data.log "ERROR, FATAL, WARN"
    
    If no file path is provided, user will be prompted to enter it.
    If no log levels are provided, user will be prompted to select them.
    """
    import sys
    
    log_file = None
    log_levels = None
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        log_file = sys.argv[1]
        # Check if there are additional arguments for log levels
        if len(sys.argv) > 2:
            # Join all remaining arguments as log levels
            log_levels = ' '.join(sys.argv[2:])
    
    if log_file is None:
        # Prompt user for file path
        print("\n" + "="*60)
        print("LOG LEVEL FILTER - File Input")
        print("="*60)
        print("\nEnter the path to the log file you want to filter:")
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
                # Try relative to current directory
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
        output_files = interactive_filter_by_log_level(log_file, log_levels)
        if output_files:
            print("\n✓ Processing complete!")
        else:
            print("\nNo files were created.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

