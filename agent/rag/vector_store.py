"""
Vector Store

Stores and retrieves embeddings using Chroma (local) or Qdrant (future).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class VectorStore(ABC):
    """Abstract base class for vector stores."""

    @abstractmethod
    def add_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        collection_name: str = "log_chunks",
    ) -> None:
        """
        Add chunks with embeddings to the vector store.

        Args:
            chunks: List of chunk dictionaries (with content, metadata, etc.).
            embeddings: List of embedding vectors.
            collection_name: Name of the collection/namespace.
        """
        pass

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        collection_name: str = "log_chunks",
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks.

        Args:
            query_embedding: Query embedding vector.
            top_k: Number of results to return.
            collection_name: Name of the collection/namespace.
            filter_dict: Optional metadata filters (e.g., {"log_level": "ERROR"}).

        Returns:
            List of chunk dictionaries with similarity scores.
        """
        pass

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None:
        """Delete a collection."""
        pass


class ChromaVectorStore(VectorStore):
    """Chroma vector store (local, persistent)."""

    def __init__(self, persist_directory: str = "output/vector_db"):
        """
        Initialize Chroma vector store.

        Args:
            persist_directory: Directory to persist Chroma database.

        Raises:
            ImportError: If chromadb package is not installed.
        """
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError:
            raise ImportError(
                "chromadb package is required for ChromaVectorStore. "
                "Install with: pip install chromadb"
            )

        os.makedirs(persist_directory, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.persist_directory = persist_directory

    def _get_collection(self, collection_name: str):
        """Get or create a collection."""
        try:
            return self.client.get_collection(name=collection_name)
        except Exception:
            return self.client.create_collection(name=collection_name)

    def add_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        collection_name: str = "log_chunks",
    ) -> None:
        """Add chunks with embeddings to Chroma."""
        if not chunks or not embeddings:
            return

        collection = self._get_collection(collection_name)

        # Prepare data for Chroma
        ids = [chunk.get("chunk_id", f"chunk_{i}") for i, chunk in enumerate(chunks)]
        documents = [chunk.get("content", "") for chunk in chunks]
        metadatas = [
            {
                "start_line": chunk.get("start_line", 0),
                "end_line": chunk.get("end_line", 0),
                "log_level": chunk.get("log_level", ""),
                "service": chunk.get("service", ""),
                "timestamp": chunk.get("timestamp", ""),
            }
            for chunk in chunks
        ]

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        collection_name: str = "log_chunks",
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for similar chunks in Chroma."""
        collection = self._get_collection(collection_name)

        # Convert filter_dict to Chroma where clause
        where = None
        if filter_dict:
            where = {}
            for key, value in filter_dict.items():
                if value:
                    where[key] = value

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )

        # Format results
        chunks = []
        if results["ids"] and len(results["ids"][0]) > 0:
            for i in range(len(results["ids"][0])):
                chunk = {
                    "chunk_id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                }
                chunks.append(chunk)

        return chunks

    def delete_collection(self, collection_name: str) -> None:
        """Delete a collection from Chroma."""
        try:
            self.client.delete_collection(name=collection_name)
        except Exception:
            pass  # Collection may not exist
