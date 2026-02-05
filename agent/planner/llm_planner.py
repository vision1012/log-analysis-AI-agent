"""
LLM Planner

LLM-based planner that uses Ollama to generate tool calls.
LLM only selects tools and arguments - no computation, parsing, or filtering in prompts.
"""

from __future__ import annotations

import os
import json
from typing import List
from agent.runtime.job_models import JobRequest, ToolCall

try:
    from agent.llm.ollama_client import OllamaClient
except ImportError:
    OllamaClient = None


def plan_llm(request: JobRequest, available_tools: List[str]) -> List[ToolCall]:
    """
    LLM-based planner that uses Ollama to generate tool calls.

    Prompts the LLM to output a JSON list of tool calls based on the query.

    Important: LLM only selects tools and arguments. All computation, parsing,
    filtering, and analysis is done by the tools themselves, not in the prompt.

    Args:
        request: JobRequest containing query and file paths.
        available_tools: List of available tool names.

    Returns:
        List of ToolCall objects.

    Raises:
        ImportError: If OllamaClient is not available.
    """
    if OllamaClient is None:
        raise ImportError(
            "OllamaClient is required for LLM planning mode. "
            "Install requests package and ensure Ollama is running."
        )

    file_path = request.file_paths[0] if request.file_paths else "unknown"

    tools_description = ", ".join(available_tools)

    prompt = f"""You are a log analysis planner. Your role is to select which tools to call based on the user's query.

Available tools: {tools_description}

User query: {request.query}
Log file: {file_path}

Your task: Select tool name(s) and provide arguments. Do NOT perform any computation, parsing, filtering, or analysis yourself - the tools will do that.

RETRIEVAL RULE: For queries that need evidence, explanation, or context understanding, you MUST FIRST call "run_retrieve_context" before other analysis tools. This includes queries asking:
- "why" (why are timeouts happening?)
- "what caused" (what caused the spike?)
- "what happened before/after" (what happened before the spike?)
- "root cause" (root cause of DB failures)
- "correlation" (correlation between errors)
- "analyze" (analyze the failures)
- "investigate" (investigate the issue)
- "explain" (explain the pattern)
- "anomaly" (detect anomalies)

DO NOT use retrieval for direct tool requests like:
- "extract all error codes" → use run_error_code_extract_all directly
- "filter by ERROR level" → use run_filter_log_level directly
- "search for keyword X" → use run_search_keyword directly
- "time slice from X to Y" → use run_time_slice directly

Output a JSON array of tool calls. Each tool call must have:
- "name": tool name (must be one of: {tools_description})
- "arguments": dict with tool-specific arguments (always include "file_path")
- "summary": brief reasoning text explaining why you selected this tool (1-2 sentences)

Example format (with retrieval for evidence-seeking query):
[
  {{
    "name": "run_retrieve_context",
    "arguments": {{"file_path": "{file_path}", "query": "{request.query}", "top_k": 8}},
    "summary": "Retrieve relevant log chunks to understand context and find evidence"
  }},
  {{
    "name": "run_log_summary",
    "arguments": {{"file_path": "{file_path}"}},
    "summary": "Generate summary after retrieving context"
  }}
]

Example format (direct tool request - NO retrieval):
[
  {{
    "name": "run_error_code_extract_all",
    "arguments": {{"file_path": "{file_path}"}},
    "summary": "Extract all error codes as requested"
  }}
]

Rules:
- Do NOT include "output_dir" in arguments (injected automatically)
- Do NOT perform any computation or analysis in your response
- Do NOT extract timestamps, error codes, or keywords yourself - use tools for that
- Only select tools and provide arguments - tools compute truth
- LLM plans + narrates; tools compute truth

Output only valid JSON, no markdown, no explanation."""

    try:
        model = os.getenv("LLAMA_MODEL", "llama3")
        client = OllamaClient(model=model)
        response = client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

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
        # Return error tool call instead of crashing
        return [
            ToolCall(
                name="unknown",
                status="pending",
                arguments={},
                summary=f"LLM planning failed: {exc}",
            )
        ]
