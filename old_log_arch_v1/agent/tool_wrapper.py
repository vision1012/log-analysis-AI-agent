"""
Tool Result Validator and Wrapper

This module provides validation and normalization of tool outputs to ensure
they conform to the ToolResult schema. This prevents broken tools from
crashing the agent.
"""

from typing import Any, Dict
from agent.schemas import ToolResult, ToolError


def validate_tool_result(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate + normalize tool output to ToolResult.
    
    Takes a raw dictionary from any run_*() function and ensures it
    conforms to the ToolResult schema. Returns a clean dict that matches
    the schema exactly.
    
    Args:
        raw: Raw dictionary output from a tool function
        
    Returns:
        Validated and normalized ToolResult as a dictionary
        
    Example:
        >>> result = run_log_summary("file.log")
        >>> validated = validate_tool_result(result)
        >>> # validated is guaranteed to match ToolResult schema
    """
    try:
        # Normalize errors if they're strings instead of ToolError dicts
        if "errors" in raw and raw["errors"]:
            normalized_errors = []
            for err in raw["errors"]:
                if isinstance(err, str):
                    normalized_errors.append({"code": "error", "message": err})
                elif isinstance(err, dict):
                    # Ensure it has required fields
                    if "code" not in err:
                        err["code"] = "error"
                    if "message" not in err:
                        err["message"] = str(err.get("details", "Unknown error"))
                    normalized_errors.append(err)
                else:
                    normalized_errors.append({"code": "error", "message": str(err)})
            raw["errors"] = normalized_errors
        
        # Normalize warnings if they're strings instead of ToolWarning dicts
        if "warnings" in raw and raw["warnings"]:
            normalized_warnings = []
            for warn in raw["warnings"]:
                if isinstance(warn, str):
                    normalized_warnings.append({"code": "warning", "message": warn})
                elif isinstance(warn, dict):
                    if "code" not in warn:
                        warn["code"] = "warning"
                    if "message" not in warn:
                        warn["message"] = str(warn.get("details", "Unknown warning"))
                    normalized_warnings.append(warn)
                else:
                    normalized_warnings.append({"code": "warning", "message": str(warn)})
            raw["warnings"] = normalized_warnings
        
        # Validate with Pydantic
        obj = ToolResult.model_validate(raw)
        return obj.model_dump()
        
    except Exception as e:
        # Fallback: never crash the agent, return a safe ToolResult
        fallback = {
            "tool": raw.get("tool", "unknown_tool"),
            "status": "error",
            "input": raw.get("input", {"file_path": "unknown", "options": {}}),
            "summary": {"headline": "Tool failed validation", "key_metrics": {}},
            "data": {"items": [], "text": None, "json": {}},
            "artifacts": [],
            "warnings": [],
            "errors": [
                {
                    "code": "schema_validation_failed",
                    "message": str(e),
                    "details": {"raw_keys": list(raw.keys())}
                }
            ],
        }
        return ToolResult.model_validate(fallback).model_dump()
