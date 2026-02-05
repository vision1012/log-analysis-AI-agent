"""
Embedder

Generates embeddings for log chunks using local sentence-transformers or OpenAI API.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

# Try to import config, but make it optional for backward compatibility
try:
    from api.config import settings
    DEFAULT_EMBEDDINGS_TIMEOUT = settings.embeddings_timeout_sec
except (ImportError, AttributeError):
    DEFAULT_EMBEDDINGS_TIMEOUT = 120


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

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", timeout_sec: Optional[int] = None):
        """
        Initialize sentence-transformers embedder.

        Args:
            model_name: Model name. Default: "all-MiniLM-L6-v2".
            timeout_sec: Timeout for embedding generation in seconds. If None, uses config value or default 120.

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
        self.timeout_sec = timeout_sec if timeout_sec is not None else DEFAULT_EMBEDDINGS_TIMEOUT

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts with timeout protection.
        
        Raises:
            RuntimeError: If embedding generation fails or times out.
        """
        def _encode():
            """Internal function to run encoding in executor."""
            return self.model.encode(texts, convert_to_numpy=False)
        
        try:
            # Use ThreadPoolExecutor to enforce timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_encode)
                embeddings = future.result(timeout=self.timeout_sec)
            
            return [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]
        except FutureTimeoutError:
            raise RuntimeError(
                f"Embedding generation timed out after {self.timeout_sec}s. "
                f"Consider increasing EMBEDDINGS_TIMEOUT_SEC or reducing batch size."
            )
        except Exception as e:
            raise RuntimeError(f"Sentence-transformers embedding failed: {e}")

    def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a single query."""
        return self.embed([query])[0]
