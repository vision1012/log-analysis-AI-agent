"""
RAG (Retrieval-Augmented Generation) Module

Provides retrieval capabilities for log analysis:
- Chunk logs with metadata (timestamps, level, service)
- Generate embeddings (local sentence-transformers)
- Store in vector database (Chroma local, Qdrant later)
- Retrieve top-K relevant chunks based on query
"""

from agent.rag.chunker import chunk_logs, Chunk
from agent.rag.embedder import Embedder, LocalSentenceTransformerEmbedder
from agent.rag.vector_store import VectorStore, ChromaVectorStore
from agent.rag.retriever import Retriever

__all__ = [
    "chunk_logs",
    "Chunk",
    "Embedder",
    "LocalSentenceTransformerEmbedder",
    "VectorStore",
    "ChromaVectorStore",
    "Retriever",
]
