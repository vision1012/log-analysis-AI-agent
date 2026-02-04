"""
Heuristic Planner

Rule-based planner that maps keywords in queries to tool calls.
No LLM required - works deterministically based on keyword matching.
"""

from __future__ import annotations

from typing import Any, Dict, List
from agent.runtime.job_models import JobRequest, ToolCall


def plan_heuristic(request: JobRequest, available_tools: List[str]) -> List[ToolCall]:
    """
    Heuristic/rule-based planner that maps keywords to tools.

    This is a simple keyword-matching approach that works without LLM.
    Returns a list of ToolCall objects ready for execution.

    Args:
        request: JobRequest containing query and file paths.
        available_tools: List of available tool names.

    Returns:
        List of ToolCall objects.
    """
    query_lower = request.query.lower()
    file_path = request.file_paths[0] if request.file_paths else None

    if not file_path:
        return [
            ToolCall(
                name="unknown",
                status="pending",
                arguments={},
                summary="No file path provided in request",
            )
        ]

    tool_calls: List[ToolCall] = []
    # Note: output_dir will be injected by ToolExecutor from JobContext
    # We don't set it here to avoid hardcoding paths

    # Check if query needs retrieval (evidence-seeking queries)
    # These patterns indicate the user wants explanation/root cause/correlation
    retrieval_keywords = [
        "why",
        "what caused",
        "what's causing",
        "what happened before",
        "what happened after",
        "root cause",
        "root-cause",
        "correlation",
        "correlate",
        "analyze",
        "understand",
        "investigate",
        "investigating",
        "explain",
        "reason",
        "spike",
        "surge",
        "anomaly",
        "anomalies",
        "pattern",
        "patterns",
        "sequence",
        "timeline",
        "before",
        "after",
        "detect",
    ]
    
    # Direct tool requests should NOT trigger retrieval
    # These are explicit commands that don't need context
    # Note: Patterns must be specific to avoid false positives
    direct_tool_patterns = [
        "extract all",
        "extract error",
        "get error codes",
        "show error codes",
        "list error codes",
        "filter by",
        "search for keyword",
        "find keyword",
        "time slice",
        "time range",
    ]
    
    # Check for time-related "between" (time range between X and Y)
    # but NOT general "between" (correlation between X and Y)
    # Use word boundaries to avoid false matches (e.g., "time" in "timeouts")
    import re
    is_time_between = (
        "between" in query_lower and 
        (re.search(r'\btime\b', query_lower) or 
         re.search(r'\brange\b', query_lower) or 
         "from" in query_lower or
         "time slice" in query_lower or
         "time range" in query_lower)
    )
    
    is_direct_tool_request = (any(pattern in query_lower for pattern in direct_tool_patterns) or 
                              is_time_between)
    needs_retrieval = any(keyword in query_lower for keyword in retrieval_keywords) and not is_direct_tool_request

    if needs_retrieval:
        tool_calls.append(
            ToolCall(
                name="run_retrieve_context",
                status="pending",
                arguments={
                    "file_path": file_path,
                    "query": request.query,
                    "top_k": 8,  # Default top_k for retrieval
                },
                summary="Retrieve relevant log chunks to understand context and find evidence",
            )
        )

    if "summary" in query_lower or "overview" in query_lower or "analyze" in query_lower:
        tool_calls.append(
            ToolCall(
                name="run_log_summary",
                status="pending",
                arguments={"file_path": file_path},
                summary="Generate log summary and health analysis",
            )
        )

    if "error" in query_lower and "code" in query_lower:
        if "all" in query_lower or "extract" in query_lower:
            tool_calls.append(
                ToolCall(
                    name="run_error_code_extract_all",
                    status="pending",
                    arguments={"file_path": file_path},
                    summary="Extract all error codes from log",
                )
            )
        else:
            tool_calls.append(
                ToolCall(
                    name="run_error_code_search",
                    status="pending",
                    arguments={
                        "file_path": file_path,
                        "error_codes": _extract_error_codes_from_query(query_lower),
                    },
                    summary="Search for specific error codes",
                )
            )

    if "error" in query_lower and "line" in query_lower:
        tool_calls.append(
            ToolCall(
                name="run_error_lines",
                status="pending",
                arguments={"file_path": file_path},
                summary="Extract error lines from log",
            )
        )

    if "stacktrace" in query_lower or "stack trace" in query_lower or "exception" in query_lower:
        tool_calls.append(
            ToolCall(
                name="run_stacktrace",
                status="pending",
                arguments={"file_path": file_path},
                summary="Extract stacktraces from log",
            )
        )

    if "time" in query_lower and ("range" in query_lower or "between" in query_lower or "from" in query_lower):
        time_range = _extract_time_range_from_query(query_lower)
        if time_range:
            tool_calls.append(
                ToolCall(
                    name="run_time_slice",
                    status="pending",
                    arguments={
                        "file_path": file_path,
                        "start_time": time_range["start"],
                        "end_time": time_range["end"],
                    },
                    summary=f"Filter logs by time range: {time_range['start']} to {time_range['end']}",
                )
            )

    if "keyword" in query_lower or "search" in query_lower or "find" in query_lower:
        keywords = _extract_keywords_from_query(query_lower)
        if keywords:
            tool_calls.append(
                ToolCall(
                    name="run_search_keyword",
                    status="pending",
                    arguments={
                        "file_path": file_path,
                        "keywords": keywords,
                    },
                    summary=f"Search for keywords: {', '.join(keywords)}",
                )
            )

    if "level" in query_lower and ("log" in query_lower or "filter" in query_lower):
        levels = _extract_log_levels_from_query(query_lower)
        if levels:
            tool_calls.append(
                ToolCall(
                    name="run_filter_log_level",
                    status="pending",
                    arguments={
                        "file_path": file_path,
                        "log_levels": levels,
                    },
                    summary=f"Filter by log levels: {', '.join(levels)}",
                )
            )

    if not tool_calls:
        tool_calls.append(
            ToolCall(
                name="run_log_summary",
                status="pending",
                arguments={"file_path": file_path},
                summary="Default: Generate log summary",
            )
        )

    return tool_calls


def _extract_error_codes_from_query(query: str) -> List[str]:
    """Extract error codes from query (simple pattern matching)."""
    import re
    codes = re.findall(r'\b[A-Z]{2,6}\d{3,4}[EI]?\b', query.upper())
    return codes[:5]


def _extract_keywords_from_query(query: str) -> List[str]:
    """Extract potential keywords from query (simple heuristic)."""
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "from"}
    words = query.split()
    keywords = [w.strip('.,!?;:"()[]{}') for w in words if w.lower() not in stop_words and len(w) > 2]
    return keywords[:5] if keywords else ["error"]


def _extract_log_levels_from_query(query: str) -> List[str]:
    """Extract log levels from query."""
    levels = []
    level_keywords = {
        "error": "ERROR",
        "warning": "WARNING",
        "warn": "WARN",
        "info": "INFO",
        "debug": "DEBUG",
        "fatal": "FATAL",
        "critical": "CRITICAL",
        "trace": "TRACE",
    }
    for keyword, level in level_keywords.items():
        if keyword in query:
            levels.append(level)
    return levels[:3]


def _extract_time_range_from_query(query: str) -> Dict[str, Any] | None:
    """Extract time range from query (placeholder - would need date parsing)."""
    from datetime import datetime, timedelta
    try:
        if "today" in query or "now" in query:
            end = datetime.now()
            start = end - timedelta(hours=1)
            return {"start": start, "end": end}
    except Exception:
        pass
    return None
