"""
Retriever

Orchestrates chunking, embedding, and vector search to retrieve relevant log chunks.
"""

from __future__ import annotations

import os
from typing import List, Dict, Any, Optional, Tuple
from agent.rag.chunker import chunk_logs, Chunk
from agent.rag.embedder import Embedder, LocalSentenceTransformerEmbedder
from agent.rag.vector_store import VectorStore, ChromaVectorStore


class Retriever:
    """Retrieves relevant log chunks based on query."""

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        vector_store: Optional[VectorStore] = None,
        persist_directory: str = "output/vector_db",
    ):
        """
        Initialize retriever.

        Args:
            embedder: Optional pre-initialized embedder. If None, creates LocalSentenceTransformerEmbedder.
            vector_store: Optional pre-initialized vector store. If None, creates ChromaVectorStore.
            persist_directory: Directory for vector store persistence.
        """
        self.embedder = embedder or LocalSentenceTransformerEmbedder()
        self.vector_store = vector_store or ChromaVectorStore(persist_directory=persist_directory)
        self.persist_directory = persist_directory

    def index_file(
        self,
        file_path: str,
        collection_name: str = "log_chunks",
        chunk_size: int = 100,
        overlap: int = 10,
        check_existing: bool = True,
        index_base_dir: str = "output/indexes",
    ) -> Tuple[int, bool]:
        """
        Index a log file by chunking and embedding it.
        
        If check_existing is True, will reuse existing index if available.

        Args:
            file_path: Path to the log file.
            collection_name: Name of the collection to store chunks.
            chunk_size: Number of lines per chunk.
            overlap: Overlapping lines between chunks.
            check_existing: Whether to check for existing index. Default: True.
            index_base_dir: Base directory for indexes. Default: "output/indexes".

        Returns:
            Tuple of (chunks_count, index_reused).
            - chunks_count: Number of chunks indexed (0 if reused)
            - index_reused: True if existing index was reused, False if new index created
        """
        from agent.rag.index_manager import (
            check_index_exists,
            get_index_vector_db_path,
            save_index_metadata,
            get_index_dir,
            compute_file_index_key,
        )
        
        # Check for existing index
        if check_existing:
            exists, index_dir, metadata = check_index_exists(
                file_path, collection_name, index_base_dir
            )
            if exists and index_dir:
                # Reuse existing index by pointing vector store to it
                vector_db_path = get_index_vector_db_path(index_dir)
                # Update persist directory and create new vector store pointing to existing index
                self.persist_directory = vector_db_path
                from agent.rag.vector_store import ChromaVectorStore
                self.vector_store = ChromaVectorStore(persist_directory=vector_db_path)
                # Return chunks count from metadata
                chunks_count = metadata.get("chunks_count", 0)
                return chunks_count, True
        
        # No existing index - create new one
        # Chunk the file
        chunks = chunk_logs(file_path, chunk_size=chunk_size, overlap=overlap)

        if not chunks:
            return 0, False

        # Convert chunks to dictionaries
        chunk_dicts = [chunk.to_dict() for chunk in chunks]

        # Generate embeddings
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embedder.embed(texts)

        # Save index metadata first
        index_key = compute_file_index_key(file_path)
        index_dir = get_index_dir(index_key, index_base_dir)
        vector_db_path = get_index_vector_db_path(index_dir)
        
        # Update vector store to use index directory
        self.persist_directory = vector_db_path
        from agent.rag.vector_store import ChromaVectorStore
        self.vector_store = ChromaVectorStore(persist_directory=vector_db_path)
        
        # Store in vector database
        self.vector_store.add_chunks(chunk_dicts, embeddings, collection_name=collection_name)
        
        # Save index metadata
        save_index_metadata(
            index_dir,
            file_path,
            index_key,
            len(chunks),
            collection_name,
        )

        return len(chunks), False

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        collection_name: str = "log_chunks",
        keyword_filter: Optional[str] = None,
        log_level_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks for a query.

        Args:
            query: Natural language query.
            top_k: Number of chunks to retrieve.
            collection_name: Name of the collection to search.
            keyword_filter: Optional keyword to filter results (post-processing).
            log_level_filter: Optional log level filter (e.g., "ERROR").

        Returns:
            List of chunk dictionaries with content and metadata.
        """
        # Generate query embedding
        query_embedding = self.embedder.embed_query(query)

        # Build filter dict
        filter_dict = {}
        if log_level_filter:
            filter_dict["log_level"] = log_level_filter

        # Search vector store
        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            collection_name=collection_name,
            filter_dict=filter_dict if filter_dict else None,
        )

        # Apply keyword filter if provided (post-processing)
        if keyword_filter and results:
            keyword_lower = keyword_filter.lower()
            filtered_results = [
                r for r in results if keyword_lower in r.get("content", "").lower()
            ]
            if filtered_results:
                results = filtered_results[:top_k]

        return results
