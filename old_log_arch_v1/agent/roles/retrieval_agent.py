"""
Retrieval Agent

Finds evidence using RAG (Retrieval-Augmented Generation).
Retrieves relevant log chunks based on query and saves to retrieval.json.
Uses run_retrieve_context tool for consistency with index reuse.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Any, Optional


class RetrievalAgent:
    """Agent responsible for retrieving relevant log chunks as evidence."""

    def __init__(
        self,
        output_dir: Optional[str] = None,
    ):
        """
        Initialize retrieval agent.

        Args:
            output_dir: Directory to save retrieval.json. If None, uses "output".
        """
        self.output_dir = output_dir or "output"

    def retrieve_evidence(
        self,
        file_path: str,
        query: str,
        top_k: int = 10,
        keyword_filter: Optional[str] = None,
        log_level_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve evidence chunks for the query using run_retrieve_context tool.

        Args:
            file_path: Path to log file to index and search.
            query: Natural language query.
            top_k: Number of chunks to retrieve.
            keyword_filter: Optional keyword filter.
            log_level_filter: Optional log level filter.

        Returns:
            Dictionary with retrieval results:
            {
                "query": str,
                "chunks_indexed": int,
                "chunks_retrieved": int,
                "chunks": List[Dict],
                "metadata": Dict,
                "index_status": str
            }
        """
        try:
            from utilities.retrieve_context import run_retrieve_context

            # Use run_retrieve_context tool (handles indexing and retrieval)
            tool_result = run_retrieve_context(
                file_path=file_path,
                query=query,
                top_k=top_k,
                output_dir=self.output_dir,
                write_file=False,  # We'll save it ourselves
                keyword_filter=keyword_filter,
                log_level_filter=log_level_filter,
            )

            if tool_result["status"] == "error":
                return {
                    "query": query,
                    "chunks_indexed": 0,
                    "chunks_retrieved": 0,
                    "chunks": [],
                    "error": tool_result.get("errors", [{}])[0].get("message", "Unknown error") if tool_result.get("errors") else "Unknown error",
                    "metadata": {
                        "file_path": file_path,
                        "top_k": top_k,
                    },
                }

            # Extract data from tool result
            data = tool_result.get("data", {})
            summary = tool_result.get("summary", {})
            key_metrics = summary.get("key_metrics", {})

            return {
                "query": query,
                "chunks_indexed": key_metrics.get("chunks_indexed", 0),
                "chunks_retrieved": key_metrics.get("chunks_retrieved", 0),
                "chunks": data.get("items", []),
                "index_status": key_metrics.get("index_status", "unknown"),
                "metadata": {
                    "file_path": file_path,
                    "top_k": top_k,
                    "keyword_filter": keyword_filter,
                    "log_level_filter": log_level_filter,
                },
            }
        except Exception as exc:
            return {
                "query": query,
                "chunks_indexed": 0,
                "chunks_retrieved": 0,
                "chunks": [],
                "error": str(exc),
                "metadata": {
                    "file_path": file_path,
                    "top_k": top_k,
                },
            }

    def save_retrieval_results(
        self, results: Dict[str, Any], output_path: str
    ) -> str:
        """
        Save retrieval results to JSON file.

        Args:
            results: Retrieval results dictionary.
            output_path: Path to save retrieval.json (absolute or relative).

        Returns:
            Absolute path to saved file.
        """
        from pathlib import Path
        import logging

        logger = logging.getLogger(__name__)
        output_path_obj = Path(output_path).resolve()
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path_obj, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        # Verify file was written and log size
        if output_path_obj.is_file():
            size_bytes = output_path_obj.stat().st_size
            logger.info(f"Wrote retrieval.json size={size_bytes} bytes to {output_path_obj}")
        else:
            logger.error(f"Failed to write retrieval.json to {output_path_obj}")
            raise RuntimeError(f"Failed to write retrieval.json to {output_path_obj}")

        return str(output_path_obj)
