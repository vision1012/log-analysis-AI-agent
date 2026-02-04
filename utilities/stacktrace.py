import re
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Union
from dataclasses import dataclass, field
from collections import Counter, defaultdict

try:
    from .tool_result import create_tool_result
except ImportError:
    from tool_result import create_tool_result


@dataclass
class Stacktrace:
    start_line: int
    end_line: int
    timestamp: Optional[datetime]
    log_level: str
    service_name: str
    error_code: Optional[str]
    exception_type: Optional[str]
    lines: List[str]
    context_before: List[str] = field(default_factory=list)
    signature: str = ""


@dataclass
class StacktraceSummary:
    total_stacktraces: int
    counts_by_exception: Dict[str, int]
    counts_by_service: Dict[str, int]
    top_frequent_traces: List[Tuple[str, int]]


ERROR_CODE_PATTERN = re.compile(r'\b([A-Z]{3,6}\d{3,4}[EI])\b')
EXCEPTION_PATTERN = re.compile(r'\b([A-Z][a-zA-Z]*(?:Exception|Error))\b')
STACKTRACE_LINE_PATTERN = re.compile(r'^\s+at\s+.+')
CAUSED_BY_PATTERN = re.compile(r'^\s*Caused by:', re.IGNORECASE)
SERVICE_PATTERN = re.compile(r'\[([A-Z][a-zA-Z]+Service)\s*-|([A-Z][a-zA-Z]+Service)\s*-|\[([A-Z][a-zA-Z]+)\]\s*-|([A-Z][a-zA-Z]+)\s*-')


def _extract_timestamp(line: str) -> Optional[datetime]:
    try:
        from dateutil import parser
        date_patterns = [
            r'\d{4}[-/]\d{2}[-/]\d{2}',
            r'\d{2}[-/]\d{2}[-/]\d{4}',
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*',
            r'\b\d{10,13}\b',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                start_idx = max(0, match.start() - 30)
                end_idx = min(len(line), match.end() + 50)
                context = line[start_idx:end_idx]
                
                try:
                    parsed = parser.parse(context, fuzzy=True, default=datetime(1970, 1, 1))
                    if 1970 < parsed.year < 2100:
                        return parsed
                except (ValueError, parser.ParserError):
                    continue
    except ImportError:
        pass
    
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
                    return datetime.strptime(clean_str[:26], fmt)
                except ValueError:
                    continue
    
    match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            pass
    
    return None


def _extract_log_level(line: str) -> Optional[str]:
    bracket_pattern = r'\[(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\]'
    match = re.search(bracket_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    colon_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE):\s*'
    match = re.search(colon_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    timestamp_log_pattern = r'(?:\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}.*?)\s+(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\b'
    match = re.search(timestamp_log_pattern, line, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None


def _extract_service(line: str) -> str:
    match = SERVICE_PATTERN.search(line)
    if match:
        for group in match.groups():
            if group:
                return group
    return "Unknown"


def _extract_error_code(line: str) -> Optional[str]:
    match = ERROR_CODE_PATTERN.search(line)
    if match:
        return match.group(1)
    return None


def _extract_exception_type(line: str) -> Optional[str]:
    match = EXCEPTION_PATTERN.search(line)
    if match:
        return match.group(1)
    return None


def _is_stacktrace_header(line: str, next_line: Optional[str] = None) -> bool:
    log_level = _extract_log_level(line)
    if log_level not in ['ERROR', 'FATAL', 'CRITICAL']:
        return False
    
    has_exception = bool(EXCEPTION_PATTERN.search(line))
    
    if next_line:
        is_followed_by_stacktrace = _is_stacktrace_line(next_line)
        if is_followed_by_stacktrace:
            return True
    
    return has_exception


def _is_stacktrace_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    
    if ' at ' in stripped and ('java:' in stripped or '.java' in stripped):
        return True
    
    if re.search(r'\s+at\s+', line):
        return True
    
    if STACKTRACE_LINE_PATTERN.match(line):
        return True
    
    if CAUSED_BY_PATTERN.match(line):
        return True
    
    if re.search(r'\bCaused by:', line, re.IGNORECASE):
        return True
    
    if re.match(r'^\s*\.\.\.\s+\d+\s+more', line, re.IGNORECASE):
        return True
    
    return False


def _normalize_signature(stacktrace_lines: List[str], top_n: int = 5) -> str:
    signature_parts = []
    for line in stacktrace_lines[:top_n]:
        if 'at ' in line:
            match = re.search(r'at\s+([^\s(]+)', line)
            if match:
                method_path = match.group(1)
                signature_parts.append(method_path)
    return ' -> '.join(signature_parts)


def _find_project_root(start_path: str) -> str:
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


def extract_stacktraces(
    filepath: str,
    include_context_lines: int = 4,
    min_stack_depth: int = 1,
    deduplicate: bool = False
) -> Tuple[List[Stacktrace], StacktraceSummary]:
    
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Log file not found: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    stacktraces: List[Stacktrace] = []
    used_line_indices = set()
    
    i = 0
    while i < len(lines):
        if i in used_line_indices:
            i += 1
            continue
        
        line = lines[i]
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        
        if _is_stacktrace_header(line, next_line):
            context_before = []
            if include_context_lines > 0:
                context_start = max(0, i - include_context_lines)
                for ctx_idx in range(context_start, i):
                    if ctx_idx not in used_line_indices:
                        context_before.append(lines[ctx_idx].rstrip('\n'))
            
            header_line = line.rstrip('\n')
            stacktrace_lines = [header_line]
            used_line_indices.add(i)
            
            timestamp = _extract_timestamp(header_line)
            log_level = _extract_log_level(header_line) or "ERROR"
            service_name = _extract_service(header_line)
            error_code = _extract_error_code(header_line)
            exception_type = _extract_exception_type(header_line)
            
            j = i + 1
            while j < len(lines):
                current_line = lines[j]
                
                if _is_stacktrace_line(current_line):
                    stacktrace_lines.append(current_line.rstrip('\n'))
                    used_line_indices.add(j)
                    j += 1
                    
                    if not exception_type:
                        exception_type = _extract_exception_type(current_line)
                else:
                    break
            
            if len(stacktrace_lines) - 1 >= min_stack_depth:
                signature = _normalize_signature(stacktrace_lines)
                
                stacktrace = Stacktrace(
                    start_line=i + 1,
                    end_line=j,
                    timestamp=timestamp,
                    log_level=log_level,
                    service_name=service_name,
                    error_code=error_code,
                    exception_type=exception_type or "UnknownException",
                    lines=stacktrace_lines,
                    context_before=context_before,
                    signature=signature
                )
                stacktraces.append(stacktrace)
            
            i = j
        else:
            i += 1
    
    if deduplicate:
        seen_signatures = {}
        deduplicated = []
        for st in stacktraces:
            if st.signature not in seen_signatures:
                seen_signatures[st.signature] = st
                deduplicated.append(st)
        stacktraces = deduplicated
    
    exception_counts = Counter()
    service_counts = Counter()
    signature_counts = Counter()
    
    for st in stacktraces:
        exception_counts[st.exception_type] += 1
        service_counts[st.service_name] += 1
        signature_counts[st.signature] += 1
    
    top_frequent = signature_counts.most_common(10)
    
    summary = StacktraceSummary(
        total_stacktraces=len(stacktraces),
        counts_by_exception=dict(exception_counts),
        counts_by_service=dict(service_counts),
        top_frequent_traces=top_frequent
    )
    
    return stacktraces, summary


def extract_stacktraces_to_files(
    filepath: str,
    include_context_lines: int = 4,
    min_stack_depth: int = 1,
    deduplicate: bool = False
) -> Dict[str, str]:
    
    stacktraces, summary = extract_stacktraces(
        filepath, include_context_lines, min_stack_depth, deduplicate
    )
    
    project_root = _find_project_root(filepath)
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    file_basename = os.path.basename(filepath)
    file_name_without_ext = os.path.splitext(file_basename)[0]
    
    clean_log_file = os.path.join(output_dir, f"{file_name_without_ext}_clean.log")
    stacktrace_file = os.path.join(output_dir, f"{file_name_without_ext}_stack_trace.log")
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        all_lines = f.readlines()
    
    used_line_indices = set()
    for st in stacktraces:
        for line_idx in range(st.start_line - 1, st.end_line):
            used_line_indices.add(line_idx)
    
    clean_lines = []
    for idx, line in enumerate(all_lines):
        if idx not in used_line_indices:
            clean_lines.append(line.rstrip('\n'))
    
    with open(clean_log_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(clean_lines))
        if clean_lines:
            f.write('\n')
    
    stacktrace_lines = []
    for st in stacktraces:
        if st.context_before:
            stacktrace_lines.extend(st.context_before)
        stacktrace_lines.extend(st.lines)
        stacktrace_lines.append('')
    
    with open(stacktrace_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(stacktrace_lines))
        if stacktrace_lines:
            f.write('\n')
    
    summary_file = os.path.join(output_dir, f"{file_name_without_ext}_stacktrace_summary.txt")
    summary_text = format_stacktrace_summary(summary)
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(summary_text)
    
    return {
        'clean_log': clean_log_file,
        'stacktraces': stacktrace_file,
        'summary': summary_file
    }


def format_stacktrace_summary(summary: StacktraceSummary) -> str:
    output = []
    output.append("=" * 80)
    output.append("STACKTRACE EXTRACTION SUMMARY")
    output.append("=" * 80)
    output.append("")
    
    output.append(f"Total Stacktraces Found: {summary.total_stacktraces}")
    output.append("")
    
    if summary.counts_by_exception:
        output.append("Exception Type Distribution:")
        output.append("-" * 80)
        for exc_type, count in sorted(summary.counts_by_exception.items(), key=lambda x: x[1], reverse=True):
            output.append(f"  {exc_type:30s} : {count:>5d}")
        output.append("")
    
    if summary.counts_by_service:
        output.append("Service Distribution:")
        output.append("-" * 80)
        for service, count in sorted(summary.counts_by_service.items(), key=lambda x: x[1], reverse=True):
            if service != "Unknown":
                output.append(f"  {service:30s} : {count:>5d}")
        output.append("")
    
    if summary.top_frequent_traces:
        output.append("Top 10 Most Frequent Stacktraces:")
        output.append("-" * 80)
        for idx, (signature, count) in enumerate(summary.top_frequent_traces, 1):
            output.append(f"  {idx:2d}. ({count} occurrences)")
            output.append(f"      {signature[:70]}")
            output.append("")
    
    output.append("=" * 80)
    
    return "\n".join(output)


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python stacktrace.py <log_file_path> [--context-lines N] [--min-depth N] [--deduplicate]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    include_context_lines = 4
    min_stack_depth = 1
    deduplicate = False
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--context-lines' and i + 1 < len(sys.argv):
            include_context_lines = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--min-depth' and i + 1 < len(sys.argv):
            min_stack_depth = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--deduplicate':
            deduplicate = True
            i += 1
        else:
            i += 1
    
    try:
        result_files = extract_stacktraces_to_files(
            filepath,
            include_context_lines=include_context_lines,
            min_stack_depth=min_stack_depth,
            deduplicate=deduplicate
        )
        
        print(f"\n✓ Stacktrace extraction complete!")
        print(f"\nOutput files:")
        print(f"  Clean log (without stacktraces): {result_files['clean_log']}")
        print(f"  Stacktraces only: {result_files['stacktraces']}")
        print(f"  Summary: {result_files['summary']}")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


def run_stacktrace(
    file_path: str,
    output_dir: str = "output",
    write_file: bool = True,
    include_context_lines: int = 4,
    min_stack_depth: int = 1,
    deduplicate: bool = False
) -> Dict:
    """
    Core function to extract stacktraces from log file.
    Returns structured dictionary with results.
    
    Args:
        file_path: Path to the log file
        output_dir: Directory to write output files (default: "output")
        write_file: Whether to write output files (default: True)
        include_context_lines: Number of context lines before stacktrace (default: 4)
        min_stack_depth: Minimum stack depth to include (default: 1)
        deduplicate: Whether to deduplicate stacktraces (default: False)
    
    Returns:
        Dictionary with:
        - success: bool
        - stacktraces: List[Stacktrace]
        - summary: StacktraceSummary
        - output_files: Dict[str, str | None] (clean_log, stacktraces, summary)
        - formatted_summary: str
        - error: str | None
    """
    input_params = {
        "file_path": file_path,
        "options": {
            "output_dir": output_dir,
            "write_file": write_file,
            "include_context_lines": include_context_lines,
            "min_stack_depth": min_stack_depth,
            "deduplicate": deduplicate
        }
    }
    
    try:
        # Validate inputs
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_stacktrace",
                status="error",
                input_params=input_params,
                errors=[f"File not found: {file_path}"]
            )
        
        # Extract stacktraces
        stacktraces, summary = extract_stacktraces(
            file_path, include_context_lines, min_stack_depth, deduplicate
        )
        
        # Format summary
        formatted_summary = format_stacktrace_summary(summary)
        
        artifacts = []
        
        if write_file:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            file_basename = os.path.basename(file_path)
            file_name_without_ext = os.path.splitext(file_basename)[0]
            
            clean_log_file = os.path.join(output_dir, f"{file_name_without_ext}_clean.log")
            stacktrace_file = os.path.join(output_dir, f"{file_name_without_ext}_stack_trace.log")
            summary_file = os.path.join(output_dir, f"{file_name_without_ext}_stacktrace_summary.txt")
            
            # Read all lines from original file
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
            
            # Create clean log (without stacktraces)
            used_line_indices = set()
            for st in stacktraces:
                for line_idx in range(st.start_line - 1, st.end_line):
                    used_line_indices.add(line_idx)
            
            clean_lines = []
            for idx, line in enumerate(all_lines):
                if idx not in used_line_indices:
                    clean_lines.append(line.rstrip('\n'))
            
            with open(clean_log_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(clean_lines))
                if clean_lines:
                    f.write('\n')
            
            artifacts.append({
                "type": "file",
                "name": f"{file_name_without_ext}_clean.log",
                "path": clean_log_file
            })
            
            # Create stacktrace file
            stacktrace_lines = []
            for st in stacktraces:
                if st.context_before:
                    stacktrace_lines.extend(st.context_before)
                stacktrace_lines.extend(st.lines)
                stacktrace_lines.append('')
            
            with open(stacktrace_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(stacktrace_lines))
                if stacktrace_lines:
                    f.write('\n')
            
            artifacts.append({
                "type": "file",
                "name": f"{file_name_without_ext}_stack_trace.log",
                "path": stacktrace_file
            })
            
            # Create summary file
            with open(summary_file, 'w', encoding='utf-8') as f:
                f.write(formatted_summary)
            
            artifacts.append({
                "type": "file",
                "name": f"{file_name_without_ext}_stacktrace_summary.txt",
                "path": summary_file
            })
        
        # Create summary
        summary_dict = {
            "headline": f"Stacktrace extraction: {len(stacktraces)} stacktraces found",
            "key_metrics": {
                "stacktrace_count": len(stacktraces),
                "total_stacktraces": summary.total_stacktraces,
                "unique_exceptions": len(summary.counts_by_exception),
                "top_exceptions": list(summary.counts_by_exception.keys())[:5]
            }
        }
        
        # Create data payload
        data = {
            "items": [{"exception": st.exception_type, "lines": st.lines} for st in stacktraces[:10]],
            "text": formatted_summary,
            "json": {
                "stacktraces": [
                    {
                        "exception_type": st.exception_type,
                        "start_line": st.start_line,
                        "end_line": st.end_line,
                        "line_count": st.line_count
                    }
                    for st in stacktraces
                ],
                "summary": {
                    "total_stacktraces": summary.total_stacktraces,
                    "counts_by_exception": summary.counts_by_exception,
                    "counts_by_service": summary.counts_by_service
                }
            }
        }
        
        return create_tool_result(
            tool="run_stacktrace",
            status="success",
            input_params=input_params,
            summary=summary_dict,
            data=data,
            artifacts=artifacts
        )
    
    except Exception as e:
        return create_tool_result(
            tool="run_stacktrace",
            status="error",
            input_params=input_params,
            errors=[str(e)]
        )


if __name__ == "__main__":
    main()
