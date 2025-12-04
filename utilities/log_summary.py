import re
import os
from datetime import datetime
from typing import Union, List, Dict, Tuple, Optional
from collections import defaultdict, Counter
from dataclasses import dataclass, field


@dataclass
class ErrorCodeInfo:
    code: str
    count: int = 0
    first_line: int = 0
    first_timestamp: Optional[datetime] = None
    last_line: int = 0
    last_timestamp: Optional[datetime] = None
    sample_message: str = ""
    service: str = ""


@dataclass
class StacktraceInfo:
    exception_type: str
    line_count: int
    first_line: int
    timestamp: Optional[datetime] = None
    services: List[str] = field(default_factory=list)


@dataclass
class LogSummary:
    total_lines: int = 0
    first_timestamp: Optional[datetime] = None
    last_timestamp: Optional[datetime] = None
    log_level_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_codes: Dict[str, ErrorCodeInfo] = field(default_factory=dict)
    stacktraces: List[StacktraceInfo] = field(default_factory=list)
    time_range_hours: float = 0.0
    error_ratio: float = 0.0
    warning_ratio: float = 0.0
    health_status: str = "UNKNOWN"
    dominant_error_code: Optional[str] = None
    root_cause_hints: List[str] = field(default_factory=list)
    high_error_windows: List[Tuple[datetime, datetime, int]] = field(default_factory=list)
    peak_error_minute: Optional[datetime] = None
    peak_error_count: int = 0
    services_involved: List[str] = field(default_factory=list)


ERROR_CODE_PATTERN = re.compile(r'\b([A-Z]{3,6}\d{3,4}[EI])\b')
STACKTRACE_LINE_PATTERN = re.compile(r'\s+at\s+.+')
EXCEPTION_PATTERN = re.compile(r'\b([A-Z][a-zA-Z]*(?:Exception|Error))\b')


ERROR_CODE_CATEGORIES = {
    'DB': ['DB', 'DATABASE', 'SQL', 'CRJAZ'],
    'NETWORK': ['NET', 'NETWORK', 'CONN', 'TIMEOUT'],
    'AUTH': ['AUTH', 'CREDENTIAL', 'LOGIN', 'PASSWORD', 'SECURITY'],
    'FILE': ['FILE', 'DISK', 'IO', 'READ', 'WRITE'],
    'DEPLOY': ['DEPLOY', 'CONTAINER', 'STARTUP'],
    'PAYMENT': ['PAY', 'PAYMENT', 'CHARGE'],
    'SHIP': ['SHIP', 'SHIPPING', 'TRACK'],
}


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
    
    space_pattern = r'\b(ERROR|ERR|FATAL|CRITICAL|WARN|WARNING|INFO|DEBUG|TRACE)\s+'
    match = re.search(space_pattern, line, re.IGNORECASE)
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


def _extract_service(line: str) -> str:
    service_patterns = [
        r'\[([A-Z][a-zA-Z]+Service)\s*-',
        r'([A-Z][a-zA-Z]+Service)\s*-',
        r'\[([A-Z][a-zA-Z]+)\]\s*-',
        r'([A-Z][a-zA-Z]+)\s*-',
    ]
    
    for pattern in service_patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(1)
    return "Unknown"


def _categorize_error_code(code: str) -> str:
    code_upper = code.upper()
    for category, keywords in ERROR_CODE_CATEGORIES.items():
        for keyword in keywords:
            if keyword in code_upper:
                return category
    return "UNKNOWN"


def _is_stacktrace_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if ' at ' in stripped and ('java:' in stripped or '.java' in stripped or stripped.startswith('at ') or re.search(r'^\s{4,}at\s', line)):
        return True
    return bool(STACKTRACE_LINE_PATTERN.search(line))


def _extract_exception_type(line: str) -> Optional[str]:
    match = EXCEPTION_PATTERN.search(line)
    if match:
        return match.group(1)
    return None


def summarize_log(log_content: Union[str, List[str]]) -> LogSummary:
    if isinstance(log_content, str):
        if os.path.isfile(log_content):
            with open(log_content, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
        elif os.path.exists(log_content):
            return LogSummary()
        elif (log_content.endswith('.log') or log_content.endswith('.txt')) and len(log_content.split()) == 1:
            return LogSummary()
        else:
            lines = log_content.splitlines(keepends=True)
    else:
        lines = [line + '\n' if not line.endswith('\n') else line for line in log_content]
    
    summary = LogSummary()
    summary.total_lines = len([l for l in lines if l.strip()])
    
    error_codes_dict: Dict[str, ErrorCodeInfo] = {}
    services_set = set()
    
    minute_error_counts: Dict[datetime, int] = defaultdict(int)
    current_stacktrace: Optional[List[str]] = None
    current_stacktrace_start_line = 0
    current_stacktrace_timestamp: Optional[datetime] = None
    current_stacktrace_service = ""
    current_stacktrace_exception: Optional[str] = None
    
    for line_num, line in enumerate(lines, 1):
        if not line.strip():
            if current_stacktrace:
                current_stacktrace = None
            continue
        
        timestamp = _extract_timestamp(line)
        log_level = _extract_log_level(line)
        service = _extract_service(line)
        is_stacktrace_line = _is_stacktrace_line(line)
        
        if service != "Unknown":
            services_set.add(service)
        
        if timestamp:
            if summary.first_timestamp is None or timestamp < summary.first_timestamp:
                summary.first_timestamp = timestamp
            if summary.last_timestamp is None or timestamp > summary.last_timestamp:
                summary.last_timestamp = timestamp
        
        if log_level and not is_stacktrace_line:
            summary.log_level_counts[log_level] += 1
        
        error_code_match = ERROR_CODE_PATTERN.search(line)
        if error_code_match:
            code = error_code_match.group(1)
            
            if code not in error_codes_dict:
                error_codes_dict[code] = ErrorCodeInfo(
                    code=code,
                    service=service
                )
            
            info = error_codes_dict[code]
            info.count += 1
            
            if info.first_line == 0:
                info.first_line = line_num
                info.first_timestamp = timestamp
                info.sample_message = line.strip()[:200]
            
            info.last_line = line_num
            info.last_timestamp = timestamp
            
            if timestamp:
                minute_key = timestamp.replace(second=0, microsecond=0)
                minute_error_counts[minute_key] += 1
        
        if is_stacktrace_line:
            if current_stacktrace is None:
                prev_line_idx = line_num - 2
                if 0 <= prev_line_idx < len(lines):
                    prev_line = lines[prev_line_idx]
                    prev_service = _extract_service(prev_line)
                    prev_timestamp = _extract_timestamp(prev_line)
                    prev_exception = _extract_exception_type(prev_line)
                else:
                    prev_line = ""
                    prev_service = ""
                    prev_timestamp = None
                    prev_exception = None
                
                current_stacktrace = [line]
                current_stacktrace_start_line = line_num
                current_stacktrace_timestamp = timestamp or prev_timestamp
                current_stacktrace_service = service if service != "Unknown" else (prev_service if prev_service != "Unknown" else "")
                current_stacktrace_exception = prev_exception
            else:
                current_stacktrace.append(line)
        else:
            if current_stacktrace:
                exception_type = current_stacktrace_exception
                if not exception_type:
                    stacktrace_text = ''.join(current_stacktrace)
                    exception_type = _extract_exception_type(stacktrace_text)
                if not exception_type:
                    exception_type = "UnknownException"
                
                stacktrace_info = StacktraceInfo(
                    exception_type=exception_type,
                    line_count=len(current_stacktrace),
                    first_line=current_stacktrace_start_line,
                    timestamp=current_stacktrace_timestamp,
                    services=[current_stacktrace_service] if current_stacktrace_service and current_stacktrace_service != "Unknown" else []
                )
                summary.stacktraces.append(stacktrace_info)
                current_stacktrace = None
                current_stacktrace_exception = None
        
        if log_level in ['ERROR', 'FATAL', 'CRITICAL'] and timestamp:
            minute_key = timestamp.replace(second=0, microsecond=0)
            minute_error_counts[minute_key] += 1
    
    if current_stacktrace:
        stacktrace_text = ''.join(current_stacktrace)
        exception_type = _extract_exception_type(stacktrace_text)
        if not exception_type:
            exception_type = "UnknownException"
        
        stacktrace_info = StacktraceInfo(
            exception_type=exception_type,
            line_count=len(current_stacktrace),
            first_line=current_stacktrace_start_line,
            timestamp=current_stacktrace_timestamp,
            services=[current_stacktrace_service] if current_stacktrace_service else []
        )
        summary.stacktraces.append(stacktrace_info)
    
    summary.error_codes = error_codes_dict
    summary.services_involved = sorted(list(services_set))
    
    if summary.first_timestamp and summary.last_timestamp:
        time_diff = summary.last_timestamp - summary.first_timestamp
        summary.time_range_hours = time_diff.total_seconds() / 3600.0
    
    total_log_lines = sum(summary.log_level_counts.values())
    error_count = summary.log_level_counts.get('ERROR', 0) + summary.log_level_counts.get('FATAL', 0) + summary.log_level_counts.get('CRITICAL', 0)
    warning_count = summary.log_level_counts.get('WARN', 0) + summary.log_level_counts.get('WARNING', 0)
    
    if total_log_lines > 0:
        summary.error_ratio = (error_count / total_log_lines) * 100
        summary.warning_ratio = (warning_count / total_log_lines) * 100
    
    if error_count > 0:
        max_code_count = 0
        for code, info in error_codes_dict.items():
            if info.count > max_code_count:
                max_code_count = info.count
                summary.dominant_error_code = code
        
        total_error_code_occurrences = sum(info.count for info in error_codes_dict.values())
        if total_error_code_occurrences > 0:
            dominant_percentage = (max_code_count / total_error_code_occurrences) * 100
            if dominant_percentage >= 70:
                category = _categorize_error_code(summary.dominant_error_code)
                summary.root_cause_hints.append(f"{dominant_percentage:.0f}% of errors are {summary.dominant_error_code} ({category} related) indicating upstream {category.lower()} failure")
    
    if minute_error_counts:
        summary.peak_error_minute = max(minute_error_counts.items(), key=lambda x: x[1])[0]
        summary.peak_error_count = minute_error_counts[summary.peak_error_minute]
        
        sorted_minutes = sorted(minute_error_counts.items(), key=lambda x: x[1], reverse=True)
        threshold = max(3, error_count // 20)
        for minute, count in sorted_minutes[:5]:
            if count >= threshold:
                from datetime import timedelta
                window_end = minute + timedelta(minutes=5)
                summary.high_error_windows.append((minute, window_end, count))
    
    if summary.error_ratio < 1.0:
        summary.health_status = "HEALTHY"
    elif summary.error_ratio < 5.0:
        summary.health_status = "WARNING"
    elif summary.error_ratio < 10.0:
        summary.health_status = "CRITICAL"
    else:
        summary.health_status = "CRITICAL"
    
    error_code_categories = Counter()
    for code, info in error_codes_dict.items():
        category = _categorize_error_code(code)
        error_code_categories[category] += info.count
    
    if error_code_categories:
        top_category = error_code_categories.most_common(1)[0]
        if top_category[1] > error_count * 0.5:
            if top_category[0] == 'DB':
                summary.root_cause_hints.append("Likely database issue - majority of errors are DB-related")
            elif top_category[0] == 'NETWORK':
                summary.root_cause_hints.append("Likely network/latency issue - majority of errors are network-related")
            elif top_category[0] == 'AUTH':
                summary.root_cause_hints.append("Likely credential/login issue - majority of errors are auth-related")
        
        if len(error_code_categories) > 1:
            sorted_cats = error_code_categories.most_common()
            if len(sorted_cats) >= 2:
                cat1, count1 = sorted_cats[0]
                cat2, count2 = sorted_cats[1]
                if cat1 == 'DB' and cat2 == 'NETWORK':
                    db_errors = [info for code, info in error_codes_dict.items() if _categorize_error_code(code) == 'DB']
                    net_errors = [info for code, info in error_codes_dict.items() if _categorize_error_code(code) == 'NETWORK']
                    if db_errors and net_errors:
                        db_last = max((info.last_timestamp for info in db_errors if info.last_timestamp), default=None)
                        net_first = min((info.first_timestamp for info in net_errors if info.first_timestamp), default=None)
                        if db_last and net_first and net_first > db_last:
                            time_diff = (net_first - db_last).total_seconds() / 60
                            if time_diff < 30:
                                summary.root_cause_hints.append(f"Network errors ({cat2}) occur shortly after DB timeouts → cascading failure likely")
    
    if summary.high_error_windows:
        if len(summary.high_error_windows) >= 2:
            summary.root_cause_hints.append("Error pattern shows multiple bursts, not continuous → suggests intermittent infrastructure issues")
        elif len(summary.high_error_windows) == 1:
            summary.root_cause_hints.append("Error pattern shows single burst → suggests isolated incident")
    
    return summary


def format_summary(summary: LogSummary, use_colors: bool = True) -> str:
    output = []
    output.append("\n" + "="*80)
    output.append("LOG SUMMARY REPORT")
    output.append("="*80 + "\n")
    
    output.append("📊 BASIC STATISTICS")
    output.append("-" * 80)
    output.append(f"Total Lines              : {summary.total_lines:,}")
    
    if summary.first_timestamp and summary.last_timestamp:
        output.append(f"Time Range               : {summary.first_timestamp.strftime('%Y-%m-%d %H:%M:%S')} → {summary.last_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        output.append(f"Duration                 : {summary.time_range_hours:.2f} hours")
    output.append("")
    
    output.append("📈 LOG LEVEL BREAKDOWN")
    output.append("-" * 80)
    level_colors = {
        'FATAL': '#FF2D00',
        'ERROR': '#FF5733',
        'WARN': '#FFA500',
        'WARNING': '#FFA500',
        'INFO': '#007BFF',
        'DEBUG': '#28A745',
        'TRACE': '#9B59B6',
    }
    
    for level in ['FATAL', 'ERROR', 'CRITICAL', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE']:
        count = summary.log_level_counts.get(level, 0)
        if count > 0:
            color_hex = level_colors.get(level, '#000000')
            output.append(f"{level:15s} : {count:>10,}  {color_hex}")
    
    output.append("")
    output.append(f"Error Ratio              : {summary.error_ratio:.2f}%")
    output.append(f"Warning Ratio            : {summary.warning_ratio:.2f}%")
    output.append("")
    
    output.append("🏥 LOG HEALTH")
    output.append("-" * 80)
    health_colors = {
        'HEALTHY': '#28A745',
        'WARNING': '#FFA500',
        'CRITICAL': '#FF5733',
    }
    health_color = health_colors.get(summary.health_status, '#000000')
    output.append(f"Status                   : {summary.health_status}  {health_color}")
    output.append("")
    
    if summary.error_codes:
        output.append("🔍 ERROR CODE ANALYSIS")
        output.append("-" * 80)
        sorted_codes = sorted(summary.error_codes.items(), key=lambda x: x[1].count, reverse=True)
        
        for code, info in sorted_codes[:10]:
            category = _categorize_error_code(code)
            output.append(f"  {code:12s} : {info.count:>5d} occurrences  [{category}]")
            if info.first_timestamp:
                output.append(f"    First seen: {info.first_timestamp.strftime('%Y-%m-%d %H:%M:%S')} (line {info.first_line})")
            if info.last_timestamp and info.last_timestamp != info.first_timestamp:
                output.append(f"    Last seen:  {info.last_timestamp.strftime('%Y-%m-%d %H:%M:%S')} (line {info.last_line})")
            if info.sample_message:
                output.append(f"    Sample:     {info.sample_message[:100]}")
            output.append("")
        
        if summary.dominant_error_code:
            dominant_info = summary.error_codes[summary.dominant_error_code]
            dominant_percentage = (dominant_info.count / sum(s.count for s in summary.error_codes.values())) * 100
            output.append(f"⚠️  Dominant Error Code: {summary.dominant_error_code} ({dominant_percentage:.1f}% of all error codes)")
            output.append("")
    
    if summary.stacktraces:
        output.append("💥 STACKTRACE ANALYSIS")
        output.append("-" * 80)
        exception_types = Counter(st.exception_type for st in summary.stacktraces)
        large_stacktraces = [st for st in summary.stacktraces if st.line_count > 10]
        all_services = set()
        for st in summary.stacktraces:
            all_services.update(st.services)
        
        output.append(f"Total Stacktraces Found      : {len(summary.stacktraces)}")
        if exception_types:
            most_common = exception_types.most_common(1)[0]
            output.append(f"Most Common Exception Type   : {most_common[0]} ({most_common[1]} occurrences)")
        output.append(f"Large Stacktrace (>10 lines)  : {len(large_stacktraces)}")
        if all_services:
            output.append(f"Services Involved            : {', '.join(sorted(all_services))}")
        output.append("")
    
    if summary.high_error_windows:
        output.append("⏰ HIGH ERROR ACTIVITY WINDOWS")
        output.append("-" * 80)
        for start_time, end_time, count in summary.high_error_windows[:5]:
            output.append(f"  {start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}   → {count} errors")
        
        if summary.peak_error_minute:
            total_spike_duration = len(summary.high_error_windows) * 5
            output.append(f"\nTotal Spike Duration: ~{total_spike_duration} minutes across the log")
        output.append("")
    
    if summary.peak_error_minute:
        output.append(f"Peak Minute                  : {summary.peak_error_minute.strftime('%H:%M')} ({summary.peak_error_count} errors)")
        output.append("")
    
    if summary.root_cause_hints:
        output.append("💡 ROOT CAUSE HINTS")
        output.append("-" * 80)
        for hint in summary.root_cause_hints:
            output.append(f"  • {hint}")
        output.append("")
    
    if summary.services_involved:
        output.append("🏢 SERVICES INVOLVED")
        output.append("-" * 80)
        output.append(f"  {', '.join(summary.services_involved)}")
        output.append("")
    
    output.append("="*80)
    
    return "\n".join(output)


def summarize_log_to_file(log_content: Union[str, List[str]], output_file: Optional[str] = None) -> str:
    summary = summarize_log(log_content)
    formatted_output = format_summary(summary, use_colors=True)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(formatted_output)
        return output_file
    else:
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt')
        temp_file.write(formatted_output)
        temp_file.close()
        return temp_file.name


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


def main():
    import sys
    
    log_file = None
    
    print("\n" + "="*60)
    print("LOG SUMMARY - File Input")
    print("="*60)
    print("\nEnter the path to the log file you want to analyze:")
    print("Example: data/sample_data.log")
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
        print(f"\nAnalyzing log file: {log_file}")
        summary = summarize_log(log_file)
        formatted_output = format_summary(summary)
        
        project_root = _find_project_root(log_file)
        output_dir = os.path.join(project_root, 'output')
        os.makedirs(output_dir, exist_ok=True)
        
        file_basename = os.path.basename(log_file)
        file_name_without_ext = os.path.splitext(file_basename)[0]
        output_filename = f"{file_name_without_ext}_log_summary.txt"
        output_path = os.path.join(output_dir, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(formatted_output)
        print(f"\n✓ Summary saved to: {output_path}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
