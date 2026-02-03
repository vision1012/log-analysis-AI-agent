"""
Pydantic Schema Definitions for ToolResult

This module provides the single source of truth for tool output contracts.
All run_*() functions must return data that validates against these schemas.
"""

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


Status = Literal["success", "error"]


class ToolWarning(BaseModel):
    """Warning information from tool execution."""
    code: str
    message: str


class ToolError(BaseModel):
    """Error information from tool execution."""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ToolArtifact(BaseModel):
    """Output artifact (file, JSON, text) created by tool."""
    type: Literal["file", "json", "text"] = "file"
    name: str
    path: str


class ToolInput(BaseModel):
    """Input parameters passed to the tool."""
    file_path: str
    options: Dict[str, Any] = Field(default_factory=dict)


class ToolSummary(BaseModel):
    """Summary information for quick display."""
    headline: str
    key_metrics: Dict[str, Any] = Field(default_factory=dict)


class ToolData(BaseModel):
    """Full data payload from tool execution."""
    items: List[Any] = Field(default_factory=list)
    text: Optional[str] = None
    json: Dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """
    Standardized tool result schema.
    
    This is the contract that all run_*() functions must follow.
    extra="forbid" prevents schema drift by rejecting unknown keys.
    """
    model_config = ConfigDict(extra="forbid")  # prevents random keys sneaking in

    tool: str
    status: Status
    input: ToolInput

    summary: ToolSummary
    data: ToolData

    artifacts: List[ToolArtifact] = Field(default_factory=list)
    warnings: List[ToolWarning] = Field(default_factory=list)
    errors: List[ToolError] = Field(default_factory=list)
