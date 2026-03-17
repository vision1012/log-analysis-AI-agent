"""
Planner Module

Determines which tools to call based on user query.
Supports both heuristic (rule-based) and LLM-based planning modes.

Developer Note:
    LLM plans + narrates; tools compute truth.
    - LLM selects tool names and arguments (planning/routing)
    - LLM composes natural language answers from tool results (narration)
    - Tools perform all computation, parsing, filtering, and analysis
    - Prompts must never contain logic for parsing, filtering, or computation
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal

from agent.runtime.job_models import JobRequest, ToolCall
from agent.runtime.tool_registry import list_tools

try:
    from agent.llm.llama_client import LLaMAClient
except ImportError:
    LLaMAClient = None


def plan_steps(
    request: JobRequest,
    tools: List[str] | None = None,
    mode: Literal["heuristic", "llm"] = "heuristic",
) -> List[ToolCall]:
    """
    Plan tool execution steps based on the job request.

    Args:
        request: JobRequest containing query and file paths.
        tools: Optional list of available tool names. If None, auto-detects from registry.
        mode: Planning mode - "heuristic" (rule-based) or "llm" (LLM-based).

    Returns:
        List of ToolCall objects ready for execution.
    """
    if tools is None:
        tools = list(list_tools().keys())

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

    if mode == "heuristic":
        return _plan_heuristic(query_lower, file_path, tools, request.options)
    elif mode == "llm":
        return _plan_llm(request, tools)
    else:
        raise ValueError(f"Unknown planning mode: {mode}")


def _plan_heuristic(
    query_lower: str,
    file_path: str,
    available_tools: List[str],
    options: Any,
) -> List[ToolCall]:
    """
    Heuristic/rule-based planner that maps keywords to tools.

    This is a simple keyword-matching approach that works without LLM.
    """
    tool_calls: List[ToolCall] = []
    # Note: output_dir will be injected by ToolExecutor from JobContext
    # We don't set it here to avoid hardcoding paths

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


def _plan_llm(request: JobRequest, available_tools: List[str]) -> List[ToolCall]:
    """
    LLM-based planner that uses LLaMA to generate tool calls.

    Prompts the LLM to output a JSON list of tool calls based on the query.

    Important: LLM only selects tools and arguments. All computation, parsing,
    filtering, and analysis is done by the tools themselves, not in the prompt.
    """
    if LLaMAClient is None:
        raise ImportError(
            "LLaMAClient is required for LLM planning mode. "
            "Install openai package and set LLAMA_API_KEY and LLAMA_BASE_URL."
        )

    file_path = request.file_paths[0] if request.file_paths else "unknown"

    tools_description = ", ".join(available_tools)

    prompt = f"""You are a log analysis planner. Your role is to select which tools to call based on the user's query.

Available tools: {tools_description}

User query: {request.query}
Log file: {file_path}

Your task: Select tool name(s) and provide arguments. Do NOT perform any computation, parsing, filtering, or analysis yourself - the tools will do that.

Output a JSON array of tool calls. Each tool call must have:
- "name": tool name (must be one of: {tools_description})
- "arguments": dict with tool-specific arguments (always include "file_path")
- "summary": brief reasoning text explaining why you selected this tool (1-2 sentences)

Example format:
[
  {{
    "name": "run_log_summary",
    "arguments": {{"file_path": "{file_path}"}},
    "summary": "User wants a summary, so I'll call run_log_summary to have the tool analyze the log"
  }}
]

Rules:
- Do NOT include "output_dir" in arguments (injected automatically)
- Do NOT perform any computation or analysis in your response
- Do NOT extract timestamps, error codes, or keywords yourself - use tools for that
- Only select tools and provide arguments - tools compute truth

Output only valid JSON, no markdown, no explanation."""

    try:
        client = LLaMAClient()
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            model=os.getenv("LLAMA_MODEL", "llama-3.1-8b"),
            temperature=0.3,
        )

        import json
        tool_calls_data = json.loads(response)

        tool_calls: List[ToolCall] = []
        for tc_data in tool_calls_data:
            if not isinstance(tc_data, dict):
                continue
            if "name" not in tc_data:
                continue

            args = tc_data.get("arguments", {})
            args.setdefault("file_path", file_path)

            tool_calls.append(
                ToolCall(
                    name=tc_data["name"],
                    status="pending",
                    arguments=args,
                    summary=tc_data.get("summary", ""),
                )
            )

        return tool_calls

    except Exception as exc:
        return [
            ToolCall(
                name="unknown",
                status="pending",
                arguments={},
                summary=f"LLM planning failed: {exc}",
            )
        ]


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
