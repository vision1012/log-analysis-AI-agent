"""
Tool Registry

Maps tool names to callable functions from utilities.
Provides helpers to list and retrieve tools.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

# Import tool functions from utilities
try:
    # When running as a package/module
    from utilities.log_summary import run_log_summary
    from utilities.time_slice import run_time_slice
    from utilities.search_on_keyword import run_search_keyword
    from utilities.filter_log_level import run_filter_log_level
    from utilities.stacktrace import run_stacktrace
    from utilities.error_code import run_error_code_search, run_error_code_extract_all
    from utilities.error_lines import run_error_lines
    from utilities.retrieve_context import run_retrieve_context
except ImportError:  # pragma: no cover - fallback for different import contexts
    # When running in a different working directory / environment
    try:
        from ..utilities.log_summary import run_log_summary  # type: ignore
        from ..utilities.time_slice import run_time_slice  # type: ignore
        from ..utilities.search_on_keyword import run_search_keyword  # type: ignore
        from ..utilities.filter_log_level import run_filter_log_level  # type: ignore
        from ..utilities.stacktrace import run_stacktrace  # type: ignore
        from ..utilities.error_code import (  # type: ignore
            run_error_code_search,
            run_error_code_extract_all,
        )
        from ..utilities.error_lines import run_error_lines  # type: ignore
        from ..utilities.retrieve_context import run_retrieve_context  # type: ignore
    except ImportError:
        # Absolute import fallback
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        from utilities.log_summary import run_log_summary
        from utilities.time_slice import run_time_slice
        from utilities.search_on_keyword import run_search_keyword
        from utilities.filter_log_level import run_filter_log_level
        from utilities.stacktrace import run_stacktrace
        from utilities.error_code import run_error_code_search, run_error_code_extract_all
        from utilities.error_lines import run_error_lines
        from utilities.retrieve_context import run_retrieve_context


# Type alias for a tool callable:
#  - Takes arbitrary keyword arguments
#  - Returns a dict (ToolResult-like structure before validation)
ToolCallable = Callable[..., Dict[str, Any]]


# Global tool registry: maps tool name -> callable
# Tool names are aligned with the `tool` field in ToolResult.
TOOL_REGISTRY: Dict[str, ToolCallable] = {
    "run_log_summary": run_log_summary,
    "run_time_slice": run_time_slice,
    "run_search_keyword": run_search_keyword,
    "run_filter_log_level": run_filter_log_level,
    "run_stacktrace": run_stacktrace,
    "run_error_code_search": run_error_code_search,
    "run_error_code_extract_all": run_error_code_extract_all,
    "run_error_lines": run_error_lines,
    "run_retrieve_context": run_retrieve_context,
}


def list_tools() -> Dict[str, str]:
    """
    List all available tools in the registry.

    Returns:
        Dict mapping tool name -> qualified function name (for debugging/introspection).
    """
    result: Dict[str, str] = {}
    for name, func in TOOL_REGISTRY.items():
        qualname = getattr(func, "__qualname__", getattr(func, "__name__", "unknown"))
        module = getattr(func, "__module__", "unknown")
        result[name] = f"{module}.{qualname}"
    return result


def get_tool(name: str) -> ToolCallable:
    """
    Retrieve a tool callable by name.

    Args:
        name: Logical tool name (e.g. 'run_log_summary').

    Returns:
        Callable that can be invoked with keyword arguments.

    Raises:
        KeyError: If the tool name is not registered.
    """
    try:
        return TOOL_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(TOOL_REGISTRY.keys()))
        raise KeyError(
            f"Unknown tool '{name}'. Available tools: {available}"
        ) from exc
