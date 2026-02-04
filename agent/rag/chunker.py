"""
Log Chunker

Chunks log files into segments with metadata (timestamps, log level, service).
Each chunk is a self-contained unit suitable for embedding and retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from dateutil import parser as date_parser


@dataclass
class Chunk:
    """A chunk of log content with metadata."""

    content: str
    start_line: int
    end_line: int
    timestamp: Optional[datetime] = None
    log_level: Optional[str] = None
    service: Optional[str] = None
    chunk_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "log_level": self.log_level,
            "service": self.service,
            "chunk_id": self.chunk_id,
        }


def chunk_logs(
    file_path: str,
    chunk_size: int = 100,
    overlap: int = 10,
    min_chunk_size: int = 20,
) -> List[Chunk]:
    """
    Chunk a log file into segments with metadata extraction.

    Args:
        file_path: Path to the log file.
        chunk_size: Number of lines per chunk (default: 100).
        overlap: Number of overlapping lines between chunks (default: 10).
        min_chunk_size: Minimum lines required for a valid chunk (default: 20).

    Returns:
        List of Chunk objects with metadata.
    """
    chunks: List[Chunk] = []

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return chunks

    if not lines:
        return chunks

    # Patterns for extracting metadata
    timestamp_patterns = [
        r"\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",  # ISO format
        r"\d{4}/\d{2}/\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?",  # Date format
        r"\[(\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]",  # Bracket format
    ]

    log_level_patterns = [
        r"\b(ERROR|WARN|WARNING|INFO|DEBUG|FATAL|CRITICAL|TRACE)\b",
        r"\[(ERROR|WARN|WARNING|INFO|DEBUG|FATAL|CRITICAL|TRACE)\]",
    ]

    service_patterns = [
        r"\[([A-Za-z0-9_-]+)\]",  # Service in brackets
        r"^([A-Za-z0-9_-]+):",  # Service prefix
    ]

    i = 0
    chunk_index = 0

    while i < len(lines):
        chunk_lines: List[str] = []
        start_line = i + 1  # 1-indexed
        chunk_timestamp: Optional[datetime] = None
        chunk_log_level: Optional[str] = None
        chunk_service: Optional[str] = None

        # Collect chunk_size lines (or remaining lines)
        end_idx = min(i + chunk_size, len(lines))
        chunk_lines = lines[i:end_idx]

        # Extract metadata from first few lines of chunk
        for line in chunk_lines[:5]:
            # Extract timestamp
            if chunk_timestamp is None:
                for pattern in timestamp_patterns:
                    match = re.search(pattern, line)
                    if match:
                        timestamp_str = match.group(1) if match.groups() else match.group(0)
                        try:
                            chunk_timestamp = date_parser.parse(timestamp_str, fuzzy=True)
                        except Exception:
                            pass
                        if chunk_timestamp:
                            break

            # Extract log level
            if chunk_log_level is None:
                for pattern in log_level_patterns:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        chunk_log_level = match.group(1) if match.groups() else match.group(0)
                        chunk_log_level = chunk_log_level.upper()
                        break

            # Extract service
            if chunk_service is None:
                for pattern in service_patterns:
                    match = re.search(pattern, line)
                    if match:
                        chunk_service = match.group(1)
                        break

        # Create chunk content
        content = "".join(chunk_lines).strip()

        # Only create chunk if it meets minimum size
        if len(chunk_lines) >= min_chunk_size:
            chunk = Chunk(
                content=content,
                start_line=start_line,
                end_line=start_line + len(chunk_lines) - 1,
                timestamp=chunk_timestamp,
                log_level=chunk_log_level,
                service=chunk_service,
                chunk_id=f"chunk_{chunk_index}",
            )
            chunks.append(chunk)
            chunk_index += 1

        # Move forward with overlap
        i += chunk_size - overlap

    return chunks
