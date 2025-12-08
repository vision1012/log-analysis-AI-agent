import tempfile

def search_keyword(log_content, keyword):
    
    """
    Search the log_content for lines containing the given keyword(s) and create a temp file with the matching lines.

    Args:
    log_content (str or list of str): The complete logs to search in.
    keyword (str or list of str): Keyword(s) to search for - case-insensitive.

    Returns:
    str: The path to the temp file containing the matching log lines.
    """
    if isinstance(keyword, str):
        keywords = [keyword]
    else:
        keywords = [str(k) for k in keyword]

    # Prepare log lines
    if isinstance(log_content, str):
        lines = log_content.splitlines()
    else:
        lines = log_content

    matched_lines = []
    for line in lines:
        if any(kw.lower() in line.lower() for kw in keywords):
            matched_lines.append(line)

    # Write results to a temp file
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
    temp_file.write('\n'.join(matched_lines))
    temp_file.close()

    return temp_file.name
