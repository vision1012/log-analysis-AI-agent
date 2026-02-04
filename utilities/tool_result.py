"""
ToolResult Schema Helper

Provides standardized ToolResult format for all run_*() functions.
This ensures consistent, agent-friendly return structures.
"""

from typing import Dict, List, Optional, Any, Union
from datetime import datetime


def create_tool_result(
    tool: str,
    status: str,  # "success" or "error"
    input_params: Dict[str, Any],
    summary: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    artifacts: Optional[List[Dict[str, str]]] = None,
    warnings: Optional[List[Dict[str, str]]] = None,
    errors: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a standardized ToolResult dictionary.
    
    Args:
        tool: Tool name (e.g., "run_log_summary")
        status: "success" or "error"
        input_params: Dictionary of input parameters
        summary: Optional summary dict with "headline" and "key_metrics"
        data: Optional data dict with "items", "text", "json"
        artifacts: Optional list of artifact dicts with "type", "name", "path"
        warnings: Optional list of warning dicts with "code" and "message"
        errors: Optional list of error strings (or single error string)
    
    Returns:
        Standardized ToolResult dictionary
    """
    # Normalize errors to list of ToolError dicts (code, message, details)
    if errors is None:
        errors_list = []
    elif isinstance(errors, str):
        errors_list = [{"code": "error", "message": errors}] if errors else []
    else:
        errors_list = []
        for err in errors:
            if isinstance(err, str):
                errors_list.append({"code": "error", "message": err})
            elif isinstance(err, dict):
                # Ensure it has code and message
                error_dict = {
                    "code": err.get("code", "error"),
                    "message": err.get("message", str(err.get("details", "Unknown error")))
                }
                if "details" in err:
                    error_dict["details"] = err["details"]
                errors_list.append(error_dict)
            else:
                errors_list.append({"code": "error", "message": str(err)})
    
    # Normalize warnings to list of dicts
    if warnings is None:
        warnings_list = []
    else:
        warnings_list = []
        for w in warnings:
            if isinstance(w, str):
                warnings_list.append({"code": "warning", "message": w})
            elif isinstance(w, dict):
                warnings_list.append(w)
    
    # Normalize artifacts to list of dicts
    if artifacts is None:
        artifacts_list = []
    else:
        artifacts_list = []
        for a in artifacts:
            if isinstance(a, str):
                # If artifact is just a path string, convert to dict
                artifacts_list.append({
                    "type": "file",
                    "name": a.split("/")[-1] if "/" in a else a.split("\\")[-1],
                    "path": a
                })
            elif isinstance(a, dict):
                artifacts_list.append(a)
    
    # Ensure summary has required structure
    if summary is None:
        summary_dict = {
            "headline": "Operation completed" if status == "success" else "Operation failed",
            "key_metrics": {}
        }
    else:
        summary_dict = {
            "headline": summary.get("headline", "Operation completed"),
            "key_metrics": summary.get("key_metrics", {})
        }
    
    # Ensure data has required structure
    if data is None:
        data_dict = {
            "items": [],
            "text": "",
            "json": {}
        }
    else:
        data_dict = {
            "items": data.get("items", []),
            "text": data.get("text", ""),
            "json": data.get("json", {})
        }
    
    return {
        "tool": tool,
        "status": status,
        "input": input_params,
        "summary": summary_dict,
        "data": data_dict,
        "artifacts": artifacts_list,
        "warnings": warnings_list,
        "errors": errors_list
    }


def format_datetime_for_summary(dt: Union[datetime, str]) -> str:
    """Format datetime for summary display."""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M:%S")
