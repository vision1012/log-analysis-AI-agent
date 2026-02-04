"""
Retrieve Context Tool

Retrieves relevant log chunks using RAG (Retrieval-Augmented Generation).
This tool indexes log files and retrieves top-K relevant chunks based on a query.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from utilities.tool_result import create_tool_result


def run_retrieve_context(
    file_path: str,
    query: str,
    top_k: int = 8,
    output_dir: Optional[str] = None,
    write_file: bool = True,
    collection_name: str = "log_chunks",
    keyword_filter: Optional[str] = None,
    log_level_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieve relevant log chunks using RAG.

    Args:
        file_path: Path to the log file to index and search.
        query: Natural language query to search for.
        top_k: Number of top chunks to retrieve (default: 8).
        output_dir: Directory to save retrieved chunks JSON file. If None, uses "output".
        write_file: Whether to write results to a file (default: True).
        collection_name: Vector store collection name (default: "log_chunks").
        keyword_filter: Optional keyword to filter results (post-processing).
        log_level_filter: Optional log level filter (e.g., "ERROR").

    Returns:
        ToolResult dictionary with retrieved chunks and metadata.
        Validated via validate_tool_result().
    """
    input_params = {
        "file_path": file_path,
        "query": query,
        "top_k": top_k,
        "write_file": write_file,
        "collection_name": collection_name,
        "keyword_filter": keyword_filter,
        "log_level_filter": log_level_filter,
    }

    try:
        # Check for missing dependencies
        try:
            from agent.rag.retriever import Retriever
        except ImportError as e:
            return create_tool_result(
                tool="run_retrieve_context",
                status="error",
                input_params=input_params,
                errors=[{
                    "code": "dependency_missing",
                    "message": f"RAG module import failed: {str(e)}. Install dependencies: pip install sentence-transformers chromadb"
                }],
            )

        # Try to initialize embedder to check for missing dependencies
        try:
            from agent.rag.embedder import LocalSentenceTransformerEmbedder
            # Test instantiation (will raise ImportError if sentence-transformers missing)
            _ = LocalSentenceTransformerEmbedder()
        except ImportError as e:
            return create_tool_result(
                tool="run_retrieve_context",
                status="error",
                input_params=input_params,
                errors=[{
                    "code": "dependency_missing",
                    "message": f"Embedder dependency missing: {str(e)}. Install with: pip install sentence-transformers"
                }],
            )

        # Try to initialize vector store to check for missing dependencies
        try:
            from agent.rag.vector_store import ChromaVectorStore
            # Test instantiation (will raise ImportError if chromadb missing)
            _ = ChromaVectorStore(persist_directory="output/vector_db")
        except ImportError as e:
            return create_tool_result(
                tool="run_retrieve_context",
                status="error",
                input_params=input_params,
                errors=[{
                    "code": "dependency_missing",
                    "message": f"Vector store dependency missing: {str(e)}. Install with: pip install chromadb"
                }],
            )

        # Validate file exists
        if not os.path.isfile(file_path):
            return create_tool_result(
                tool="run_retrieve_context",
                status="error",
                input_params=input_params,
                errors=[{"code": "file_not_found", "message": f"File not found: {file_path}"}],
            )

        # Determine persist directory (for vector DB)
        # If output_dir is provided, use it; otherwise use default
        if output_dir:
            persist_dir = os.path.join(output_dir, "vector_db")
        else:
            persist_dir = "output/vector_db"

        # Initialize retriever (uses LocalSentenceTransformerEmbedder and ChromaVectorStore by default)
        retriever = Retriever(persist_directory=persist_dir)

        # Index the file (check for existing index and reuse if available)
        chunks_indexed, index_reused = retriever.index_file(
            file_path,
            collection_name=collection_name,
            check_existing=True,
        )

        # Retrieve relevant chunks
        retrieved_chunks = retriever.retrieve(
            query=query,
            top_k=top_k,
            collection_name=collection_name,
            keyword_filter=keyword_filter,
            log_level_filter=log_level_filter,
        )

        # Prepare output file path
        # If output_dir is provided and looks like a job directory, save as retrieval.json
        # Otherwise, use a descriptive filename
        output_file_path = None
        if write_file:
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                # Check if output_dir looks like a job directory (contains "jobs" in path)
                if "jobs" in output_dir:
                    # Save as retrieval.json in job directory
                    output_file_path = os.path.join(output_dir, "retrieval.json")
                else:
                    # Use descriptive filename
                    safe_query = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in query)[:50]
                    output_file_path = os.path.join(
                        output_dir, f"retrieved_chunks_{safe_query.replace(' ', '_')}.json"
                    )
            else:
                # Default output directory
                default_output = "output"
                os.makedirs(default_output, exist_ok=True)
                safe_query = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in query)[:50]
                output_file_path = os.path.join(
                    default_output, f"retrieved_chunks_{safe_query.replace(' ', '_')}.json"
                )

            # Write retrieved chunks to JSON
            if output_file_path:
                with open(output_file_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "query": query,
                            "top_k": top_k,
                            "chunks_indexed": chunks_indexed,
                            "chunks_retrieved": len(retrieved_chunks),
                            "chunks": retrieved_chunks,
                        },
                        f,
                        indent=2,
                        default=str,
                    )

        # Build summary with index hit/miss metrics
        index_status = "index_hit" if index_reused else "index_miss"
        summary = {
            "headline": f"Retrieved {len(retrieved_chunks)} relevant chunks",
            "key_metrics": {
                "chunks_indexed": chunks_indexed,
                "chunks_retrieved": len(retrieved_chunks),
                "query": query,
                "index_status": index_status,
                "index_hit": index_reused,
                "index_miss": not index_reused,
            },
        }

        # Build data
        data = {
            "items": retrieved_chunks,
            "text": f"Retrieved {len(retrieved_chunks)} chunks for query: {query}",
            "json": {
                "query": query,
                "top_k": top_k,
                "chunks_indexed": chunks_indexed,
                "chunks_retrieved": len(retrieved_chunks),
                "index_status": index_status,
                "index_reused": index_reused,
            },
        }

        # Build artifacts
        artifacts = []
        if output_file_path:
            artifacts.append(
                {
                    "type": "json",
                    "name": os.path.basename(output_file_path),
                    "path": output_file_path,
                }
            )

        result = create_tool_result(
            tool="run_retrieve_context",
            status="success",
            input_params=input_params,
            summary=summary,
            data=data,
            artifacts=artifacts,
        )

        # Validate via validate_tool_result
        from agent.tool_wrapper import validate_tool_result
        return validate_tool_result(result)

    except Exception as exc:
        # Catch any other exceptions and return error ToolResult
        error_code = "retrieval_error"
        error_message = str(exc)
        
        # Check if it's a dependency-related error
        if "ImportError" in str(type(exc)) or "No module named" in error_message:
            error_code = "dependency_missing"
            error_message = f"Dependency missing: {error_message}. Install with: pip install sentence-transformers chromadb"
        
        result = create_tool_result(
            tool="run_retrieve_context",
            status="error",
            input_params=input_params,
            errors=[{"code": error_code, "message": error_message}],
        )
        
        # Validate error result too
        from agent.tool_wrapper import validate_tool_result
        return validate_tool_result(result)