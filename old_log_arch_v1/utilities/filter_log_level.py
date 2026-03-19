import re
import os
import tempfile
from typing import Union, List, Dict, Optional

try:
    from .tool_result import create_tool_result
except ImportError:
    from tool_result import create_tool_result


def filter_by_log_level(log_content: Union[str, List[str]], log_levels: Union[str, List[str]]) -> List[str]:
    
    if isinstance(log_levels, str):
        log_levels = [log_levels]
    else:
        log_levels = [str(level) for level in log_levels]
    
    log_levels_normalized = [level.upper() for level in log_levels]
    
    if isinstance(log_content, str) and os.path.isfile(log_content):
        with open(log_content, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    elif isinstance(log_content, str):
        lines = log_content.splitlines()
    else:
        lines = log_content
    
    filtered_lines = []
    
    for line in lines:
        if not line.strip():
            continue
        
        log_level = _extract_log_level(line)
        
        if log_level is None:
            continue
        
        if log_level.upper() in log_levels_normalized:
            filtered_lines.append(line.rstrip('\n'))
    
    return filtered_lines


def _extract_log_level(line: str) -> Union[str, None]:
    bracket_pattern = r'\[(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\]'
    match = re.search(bracket_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    colon_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE):\s*'
    match = re.search(colon_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    space_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s+'
    match = re.search(space_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    dash_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s*-\s*'
    match = re.search(dash_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    log4j_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s{2,}'
    match = re.search(log4j_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    timestamp_log_pattern = r'(?:\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}.*?)\s+(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    match = re.search(timestamp_log_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    simple_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    matches = re.findall(simple_pattern, line, re.IGNORECASE)
    if matches:
        for level in ['ERROR', 'FATAL', 'CRITICAL', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']:
            if level in [m.upper() for m in matches]:
                return level
    
    return None


def run_filter_log_level(
    file_path: str,
    log_levels: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True
) -> Dict:
    """
    Core function to filter log file by log level(s).
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        log_levels: Single log level string or list of log levels
        output_dir: Directory to write output files (default: "output")
        write_file: Whether to write output files (default: True)
    
    Returns:
        Dictionary with:
        - success: bool
        - filtered_lines: List[str] (all filtered lines combined)
        - output_files: List[str] (one file per level)
        - counts_by_level: Dict[str, int]
        - error: str | None
    """
    # Normalize log levels to list
    if isinstance(log_levels, str):
        log_levels_list = [log_levels]
    else:
        log_levels_list = [str(level) for level in log_levels] if log_levels else []
    
    log_levels_normalized = [level.upper() for level in log_levels_list]
    
    input_params = {
        "file_path": file_path,
        "log_levels": log_levels_normalized,
        "options": {
            "output_dir": output_dir,
            "write_file": write_file
        }
    }
    
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_filter_log_level",
                status="error",
                input_params=input_params,
                errors=[f"File not found: {file_path}"]
            )
        
        # Filter lines by log level
        all_filtered_lines = []
        counts_by_level = {}
        artifacts = []
        
        file_basename = os.path.basename(file_path)
        file_name_without_ext = os.path.splitext(file_basename)[0]
        
        for level in log_levels_normalized:
            filtered_lines = filter_by_log_level(file_path, level)
            counts_by_level[level] = len(filtered_lines)
            all_filtered_lines.extend(filtered_lines)
            
            if write_file and filtered_lines:
                # Create output directory if it doesn't exist
                os.makedirs(output_dir, exist_ok=True)
                
                output_filename = f"{file_name_without_ext}_{level}.log"
                output_path = os.path.join(output_dir, output_filename)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(filtered_lines))
                    if filtered_lines:
                        f.write('\n')
                
                artifacts.append({
                    "type": "file",
                    "name": output_filename,
                    "path": output_path
                })
        
        # Create summary
        total_lines = sum(counts_by_level.values())
        levels_display = ', '.join(log_levels_normalized)
        summary = {
            "headline": f"Log level filter: {total_lines} lines found across {len(log_levels_normalized)} level(s)",
            "key_metrics": {
                "total_lines": total_lines,
                "levels_filtered": log_levels_normalized,
                "counts_by_level": counts_by_level
            }
        }
        
        # Create data payload
        data = {
            "items": all_filtered_lines,
            "text": f"Filtered {total_lines} lines by log levels: {levels_display}",
            "json": {
                "filtered_lines": all_filtered_lines,
                "counts_by_level": counts_by_level
            }
        }
        
        return create_tool_result(
            tool="run_filter_log_level",
            status="success",
            input_params=input_params,
            summary=summary,
            data=data,
            artifacts=artifacts
        )
    
    except Exception as e:
        return create_tool_result(
            tool="run_filter_log_level",
            status="error",
            input_params=input_params,
            errors=[str(e)]
        )


def filter_by_log_level_to_file(log_content: Union[str, List[str]], log_levels: Union[str, List[str]], output_file: Union[str, None] = None) -> str:
    filtered_lines = filter_by_log_level(log_content, log_levels)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(filtered_lines))
        return output_file
    else:
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
        temp_file.write('\n'.join(filtered_lines))
        temp_file.close()
        return temp_file.name


def interactive_filter_by_log_level(log_file: str, log_levels: Union[str, List[str], None] = None) -> List[str]:
    if not os.path.isfile(log_file):
        raise FileNotFoundError(f"Log file not found: {log_file}")
    
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
    
    output_dir = os.path.join(base_dir, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    file_basename = os.path.basename(log_file)
    file_name_without_ext = os.path.splitext(file_basename)[0]
    
    available_levels = ['ERROR', 'FATAL', 'CRITICAL', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']
    
    selected_levels = []
    
    print("\n" + "="*60)
    print("LOG LEVEL FILTER - Interactive Mode")
    print("="*60)
    print(f"\nProcessing file: {log_file}")
    print(f"\nAvailable log levels:")
    print("-" * 60)
    for i, level in enumerate(available_levels, 1):
        print(f"  {i}. {level}")
    print("-" * 60)
    
    print("\nEnter the NUMBER(s) of log level(s) to filter:")
    print("Example: 1,2,3  or  1 2 3  or  just  1")
    print("Type 'all' to filter all levels")
    print("Type 'quit' to exit")
    
    user_input = input("\nEnter number(s): ").strip()
    
    if user_input.lower() in ['quit', 'exit', 'q']:
        print("Exiting...")
        return []
    
    if user_input.lower() == 'all':
        selected_levels = available_levels
    else:
        parts = re.split(r'[,;\s]+', user_input)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(available_levels):
                    selected_levels.append(available_levels[idx])
                else:
                    print(f"Warning: '{part}' is not a valid number. Please enter a number between 1 and {len(available_levels)}.")
            else:
                print(f"Warning: '{part}' is not a valid number. Please enter a number between 1 and {len(available_levels)}.")
    
    seen = set()
    selected_levels = [x for x in selected_levels if not (x in seen or seen.add(x))]
    
    if not selected_levels:
        print("No valid log levels selected. Exiting...")
        return []
    
    print(f"\nSelected log levels: {', '.join(selected_levels)}")
    print(f"Output directory: {output_dir}")
    print("\nProcessing...")
    
    output_files = []
    
    for level in selected_levels:
        output_filename = f"{file_name_without_ext}_{level}.log"
        output_path = os.path.join(output_dir, output_filename)
        
        filtered_lines = filter_by_log_level(log_file, level)
        
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
    import sys
    
    log_file = None
    
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
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(script_dir)
        current_dir = os.getcwd()
        basename = os.path.basename(user_file_input)
        
        possible_paths = [
            user_file_input,
            os.path.join(current_dir, user_file_input),
            os.path.join(script_dir, user_file_input),
            os.path.join(parent_dir, user_file_input),
            os.path.join(script_dir, basename),
            os.path.join(parent_dir, basename),
        ]
        
        if "utilities" in user_file_input and not user_file_input.startswith("/"):
            if user_file_input.startswith("utilities/"):
                possible_paths.append(os.path.join(parent_dir, user_file_input))
                possible_paths.append(os.path.join(script_dir, user_file_input.replace("utilities/", "")))
        
        seen = set()
        possible_paths = [p for p in possible_paths if p not in seen and not seen.add(p)]
        
        found = False
        for path in possible_paths:
            if os.path.isfile(path):
                log_file = path
                found = True
                print(f"✓ Found file: {path}")
                break
        
        if found:
            break
        else:
            print(f"\nError: File not found: {user_file_input}")
            print("\nTip: Try one of these:")
            print(f"  - {basename}  (if file is in current directory)")
            print(f"  - ../{user_file_input}  (if running from utilities/ directory)")
            print(f"  - Full absolute path")
            print("\nPlease check the path and try again, or type 'quit' to exit.")
    
    try:
        output_files = interactive_filter_by_log_level(log_file, None)
        if output_files:
            print("\n✓ Processing complete!")
        else:
            print("\nNo files were created.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

