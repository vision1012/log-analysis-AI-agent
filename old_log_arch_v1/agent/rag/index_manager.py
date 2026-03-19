"""
Index Manager

Manages persistent indexes for log files to avoid re-embedding the same file.
Uses file hash (path + mtime + size) as index key.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


def compute_file_index_key(file_path: str) -> str:
    """
    Compute a stable index key for a file.
    
    Uses hash of: file path (absolute) + modified time + file size.
    This ensures the key changes if the file is modified.
    
    Args:
        file_path: Path to the file.
        
    Returns:
        Hex digest of the hash (32 characters).
    """
    try:
        stat = os.stat(file_path)
        # Use absolute path for consistency
        abs_path = os.path.abspath(file_path)
        # Combine: path + mtime + size
        key_data = f"{abs_path}|{stat.st_mtime}|{stat.st_size}"
        hash_obj = hashlib.md5(key_data.encode())
        return hash_obj.hexdigest()
    except Exception:
        # Fallback: use path only if stat fails
        abs_path = os.path.abspath(file_path)
        hash_obj = hashlib.md5(abs_path.encode())
        return hash_obj.hexdigest()


def get_index_dir(index_key: str, base_dir: str = "output/indexes") -> str:
    """
    Get the directory path for an index.
    
    Args:
        index_key: Index key (file hash).
        base_dir: Base directory for indexes. Default: "output/indexes".
        
    Returns:
        Full path to the index directory.
    """
    return os.path.join(base_dir, index_key)


def get_index_metadata_path(index_dir: str) -> str:
    """
    Get the path to the index metadata file.
    
    Args:
        index_dir: Index directory path.
        
    Returns:
        Path to index_metadata.json.
    """
    return os.path.join(index_dir, "index_metadata.json")


def load_index_metadata(index_dir: str) -> Optional[Dict]:
    """
    Load index metadata from disk.
    
    Args:
        index_dir: Index directory path.
        
    Returns:
        Metadata dictionary or None if not found.
    """
    metadata_path = get_index_metadata_path(index_dir)
    if not os.path.isfile(metadata_path):
        return None
    
    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_index_metadata(
    index_dir: str,
    file_path: str,
    index_key: str,
    chunks_count: int,
    collection_name: str,
) -> str:
    """
    Save index metadata to disk.
    
    Args:
        index_dir: Index directory path.
        file_path: Original file path.
        index_key: Index key (file hash).
        chunks_count: Number of chunks indexed.
        collection_name: Collection name used.
        
    Returns:
        Path to the saved metadata file.
    """
    os.makedirs(index_dir, exist_ok=True)
    
    metadata = {
        "file_path": os.path.abspath(file_path),
        "index_key": index_key,
        "chunks_count": chunks_count,
        "collection_name": collection_name,
        "created_at": datetime.now().isoformat(),
        "index_version": "1.0.0",
    }
    
    metadata_path = get_index_metadata_path(index_dir)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    
    return metadata_path


def check_index_exists(
    file_path: str,
    collection_name: str = "log_chunks",
    base_dir: str = "output/indexes",
) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    Check if an index exists for a file.
    
    Args:
        file_path: Path to the file.
        collection_name: Collection name to check.
        base_dir: Base directory for indexes.
        
    Returns:
        Tuple of (exists, index_dir, metadata).
        - exists: True if index exists and is valid
        - index_dir: Path to index directory if exists, None otherwise
        - metadata: Metadata dict if exists, None otherwise
    """
    index_key = compute_file_index_key(file_path)
    index_dir = get_index_dir(index_key, base_dir)
    metadata = load_index_metadata(index_dir)
    
    if not metadata:
        return False, None, None
    
    # Check if metadata matches
    if metadata.get("collection_name") != collection_name:
        return False, None, None
    
    # Check if file path matches (should match, but verify)
    abs_file_path = os.path.abspath(file_path)
    if metadata.get("file_path") != abs_file_path:
        # File path changed but hash matches? Unlikely but possible
        # Still consider it valid if hash matches
        pass
    
    # Check if index directory exists
    if not os.path.isdir(index_dir):
        return False, None, None
    
    return True, index_dir, metadata


def get_index_vector_db_path(index_dir: str) -> str:
    """
    Get the path to the vector database within an index directory.
    
    Args:
        index_dir: Index directory path.
        
    Returns:
        Path to vector_db subdirectory.
    """
    return os.path.join(index_dir, "vector_db")
