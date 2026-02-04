"""
Embedder

Generates embeddings for log chunks using local sentence-transformers or OpenAI API.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List


class Embedder(ABC):
    """Abstract base class for embedding generators."""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of floats).
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> List[float]:
        """
        Generate embedding for a single query string.

        Args:
            query: Query string to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        pass


class LocalSentenceTransformerEmbedder(Embedder):
    """Local sentence-transformers embeddings (no API required)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize sentence-transformers embedder.

        Args:
            model_name: Model name. Default: "all-MiniLM-L6-v2".

        Raises:
            ImportError: If sentence-transformers package is not installed.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers package is required for LocalSentenceTransformerEmbedder. "
                "Install with: pip install sentence-transformers"
            )

        self.model = SentenceTransformer(model_name)
        self.model_name = model_name

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        try:
            embeddings = self.model.encode(texts, convert_to_numpy=False)
            return [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]
        except Exception as e:
            raise RuntimeError(f"Sentence-transformers embedding failed: {e}")

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a single query."""
        return self.embed([query])[0]
