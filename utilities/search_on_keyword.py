import tempfile

def search_keyword(log_content, keyword):
    
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