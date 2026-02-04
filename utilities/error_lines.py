import re
import os
from typing import Union, List, Dict, Optional

try:
    from .tool_result import create_tool_result
except ImportError:
    from tool_result import create_tool_result


def get_error_lines(log_content: Union[str, List[str]]) -> List[str]:
    """
    Extract lines containing error log levels from log content.
    
    Args:
        log_content: Log file path, log content as string, or list of log lines.
    
    Returns:
        List of error log lines.
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
    
    error_lines = []
    error_levels = ['ERROR', 'ERR', 'FATAL', 'CRITICAL']
    
    for line in lines:
        if not line.strip():
            continue
        
        # Check for error log levels
        line_upper = line.upper()
        for level in error_levels:
            if f'[{level}]' in line_upper or f'{level}:' in line_upper or f' {level} ' in line_upper:
                error_lines.append(line.rstrip('\n'))
                break
    
    return error_lines


def run_error_lines(
    file_path: str,
    output_dir: str = "output",
    write_file: bool = True
) -> Dict:
    """
    Core function to extract error lines from log file.
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        output_dir: Directory to write output file (default: "output")
        write_file: Whether to write output file (default: True)
    
    Returns:
        Dictionary with:
        - success: bool
        - error_lines: List[str]
        - output_file: str | None
        - error_count: int
        - error: str | None
    """
    input_params = {
        "file_path": file_path,
        "options": {
            "output_dir": output_dir,
            "write_file": write_file
        }
    }
    
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_error_lines",
                status="error",
                input_params=input_params,
                errors=[f"File not found: {file_path}"]
            )
        
        # Extract error lines
        error_lines = get_error_lines(file_path)
        
        artifacts = []
        output_file = None
        if write_file and error_lines:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate output filename
            file_basename = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            output_filename = f"{file_name_without_ext}_ERROR.log"
            output_file = os.path.join(output_dir, output_filename)
            
            # Write to file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(error_lines))
                if error_lines:
                    f.write('\n')
            
            artifacts.append({
                "type": "file",
                "name": output_filename,
                "path": output_file
            })
        
        # Create summary
        summary = {
            "headline": f"Error lines extraction: {len(error_lines)} error lines found",
            "key_metrics": {
                "error_count": len(error_lines),
                "file": os.path.basename(file_path)
            }
        }
        
        # Create data payload
        data = {
            "items": error_lines,
            "text": f"Extracted {len(error_lines)} error lines from log file",
            "json": {
                "error_lines": error_lines,
                "error_count": len(error_lines)
            }
        }
        
        return create_tool_result(
            tool="run_error_lines",
            status="success",
            input_params=input_params,
            summary=summary,
            data=data,
            artifacts=artifacts
        )
    
    except Exception as e:
        return create_tool_result(
            tool="run_error_lines",
            status="error",
            input_params=input_params,
            errors=[str(e)]
        )
