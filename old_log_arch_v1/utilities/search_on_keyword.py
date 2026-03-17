import os
import re
from typing import Union, List, Dict, Optional

try:
    from .tool_result import create_tool_result
except ImportError:
    from tool_result import create_tool_result


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


def search_keyword(log_content, keyword):
    
    if isinstance(keyword, str):
        keywords = [keyword]
    else:
        keywords = [str(k) for k in keyword]

    # Prepare log lines
    if isinstance(log_content, str) and os.path.isfile(log_content):
        with open(log_content, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    elif isinstance(log_content, str):
        lines = log_content.splitlines()
    else:
        lines = log_content

    matched_lines = []
    for line in lines:
        if any(kw.lower() in line.lower() for kw in keywords):
            matched_lines.append(line.rstrip('\n'))

    # Create output directory
    project_root = _find_project_root()
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename from keyword(s)
    # If multiple keywords, join them with underscore
    keyword_str = '_'.join(keywords)
    # Sanitize filename: replace invalid characters with underscore
    keyword_str = re.sub(r'[<>:"/\\|?*]', '_', keyword_str)
    keyword_str = re.sub(r'\s+', '_', keyword_str)  # Replace spaces with underscore
    keyword_str = keyword_str[:50]  # Limit length to 50 characters
    
    output_filename = f"keyword_{keyword_str}.log"
    output_path = os.path.join(output_dir, output_filename)

    # Write results to output file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(matched_lines))
        if matched_lines:
            f.write('\n')

    return output_path


def run_search_keyword(
    file_path: str,
    keywords: Union[str, List[str]],
    output_dir: str = "output",
    write_file: bool = True,
    case_sensitive: bool = False
) -> Dict:
    """
    Core function to search log file by keyword(s).
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        keywords: Single keyword string or list of keywords
        output_dir: Directory to write output file (default: "output")
        write_file: Whether to write output file (default: True)
        case_sensitive: Whether search should be case-sensitive (default: False)
    
    Returns:
        Dictionary with:
        - success: bool
        - matched_lines: List[str]
        - output_file: str | None
        - keywords: List[str]
        - match_count: int
        - error: str | None
    """
    # Normalize keywords to list
    if isinstance(keywords, str):
        keywords_list = [keywords]
    else:
        keywords_list = [str(k) for k in keywords] if keywords else []
    
    input_params = {
        "file_path": file_path,
        "keywords": keywords_list,
        "options": {
            "output_dir": output_dir,
            "write_file": write_file,
            "case_sensitive": case_sensitive
        }
    }
    
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_search_keyword",
                status="error",
                input_params=input_params,
                errors=[f"File not found: {file_path}"]
            )
        
        if not keywords_list:
            return create_tool_result(
                tool="run_search_keyword",
                status="error",
                input_params=input_params,
                errors=["No keywords provided"]
            )
        
        # Read log file
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        # Search for keywords
        matched_lines = []
        for line in lines:
            line_stripped = line.rstrip('\n')
            if case_sensitive:
                if any(kw in line_stripped for kw in keywords_list):
                    matched_lines.append(line_stripped)
            else:
                if any(kw.lower() in line_stripped.lower() for kw in keywords_list):
                    matched_lines.append(line_stripped)
        
        artifacts = []
        output_file = None
        if write_file:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Generate filename from keyword(s)
            keyword_str = '_'.join(keywords_list)
            # Sanitize filename
            keyword_str = re.sub(r'[<>:"/\\|?*]', '_', keyword_str)
            keyword_str = re.sub(r'\s+', '_', keyword_str)
            keyword_str = keyword_str[:50]  # Limit length
            
            output_filename = f"keyword_{keyword_str}.log"
            output_file = os.path.join(output_dir, output_filename)
            
            # Write results to output file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(matched_lines))
                if matched_lines:
                    f.write('\n')
            
            artifacts.append({
                "type": "file",
                "name": output_filename,
                "path": output_file
            })
        
        # Create summary
        keywords_display = ', '.join(keywords_list[:3])
        if len(keywords_list) > 3:
            keywords_display += f" (+{len(keywords_list) - 3} more)"
        
        summary = {
            "headline": f"Keyword search: {len(matched_lines)} matches found",
            "key_metrics": {
                "match_count": len(matched_lines),
                "keywords_searched": len(keywords_list),
                "keywords": keywords_display,
                "case_sensitive": case_sensitive
            }
        }
        
        # Create data payload
        data = {
            "items": matched_lines,
            "text": f"Found {len(matched_lines)} lines matching keywords: {keywords_display}",
            "json": {
                "matched_lines": matched_lines,
                "keywords": keywords_list,
                "match_count": len(matched_lines)
            }
        }
        
        return create_tool_result(
            tool="run_search_keyword",
            status="success",
            input_params=input_params,
            summary=summary,
            data=data,
            artifacts=artifacts
        )
    
    except Exception as e:
        return create_tool_result(
            tool="run_search_keyword",
            status="error",
            input_params=input_params,
            errors=[str(e)]
        )