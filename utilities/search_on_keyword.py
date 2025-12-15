import os
import re


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