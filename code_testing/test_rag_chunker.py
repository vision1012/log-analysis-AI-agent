"""
Unit Tests for RAG Chunker

Tests chunk_logs() function output shape and basic functionality.
"""

import unittest
import tempfile
import os
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.rag.chunker import chunk_logs, Chunk


class TestRAGChunker(unittest.TestCase):
    """Test cases for chunk_logs function."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        # Create a longer test log to ensure chunks are created (min_chunk_size=20)
        base_log_lines = [
            "2025-01-12 09:15:02 [INFO] AuthService - User login initiated user=jay",
            "2025-01-12 09:15:03 [DEBUG] AuthService - Validating credentials",
            "2025-01-12 09:15:04 [WARN] InventoryService - Stock low for SKU=1223",
            "2025-01-12 09:15:05 [ERROR] DBService - CRJAZ1282E Database connection failure",
            "2025-01-12 09:15:05     at com.db.Driver.connect(Driver.java:88)",
            "2025-01-12 09:15:05     at com.db.ConnectionPool.getConnection(ConnectionPool.java:130)",
            "2025-01-12 09:15:06 [DEBUG] DBService - Retrying connection attempt 1",
            "2025-01-12 09:15:07 [ERROR] DBService - CRJAZ1282E Timeout after 5000ms",
            "2025-01-12 09:15:08 [INFO] NotificationService - Email sent user=jay",
            "2025-01-12 09:15:09 [INFO] ReportService - Generating weekly report",
            "2025-01-12 09:15:10 [ERROR] ReportService - RPT9002E Report generation timeout",
            "2025-01-12 09:15:10     at com.report.Builder.generate(Builder.java:210)",
            "2025-01-12 09:15:11 [DEBUG] System - Running cron cleanup",
            "2025-01-12 09:15:12 [INFO] System - Cleanup completed",
        ]
        # Repeat to get at least 30 lines (above min_chunk_size=20)
        self.test_log_content = "\n".join(base_log_lines * 3)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_chunk_logs_returns_list_of_chunks(self):
        """Test that chunk_logs returns a list of Chunk objects."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        chunks = chunk_logs(test_file)

        self.assertIsInstance(chunks, list)
        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)

    def test_chunk_has_required_attributes(self):
        """Test that each Chunk has required attributes."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        chunks = chunk_logs(test_file)

        self.assertGreater(len(chunks), 0)
        chunk = chunks[0]

        # Required attributes
        self.assertIsInstance(chunk.content, str)
        self.assertIsInstance(chunk.start_line, int)
        self.assertIsInstance(chunk.end_line, int)
        self.assertGreater(chunk.start_line, 0)
        self.assertGreaterEqual(chunk.end_line, chunk.start_line)

        # Optional attributes (may be None)
        if chunk.timestamp is not None:
            self.assertIsInstance(chunk.timestamp, type(chunk.timestamp))
        if chunk.log_level is not None:
            self.assertIsInstance(chunk.log_level, str)
        if chunk.service is not None:
            self.assertIsInstance(chunk.service, str)
        if chunk.chunk_id is not None:
            self.assertIsInstance(chunk.chunk_id, str)

    def test_chunk_to_dict_serialization(self):
        """Test that chunk.to_dict() returns a serializable dictionary."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        chunks = chunk_logs(test_file)

        self.assertGreater(len(chunks), 0)
        chunk_dict = chunks[0].to_dict()

        self.assertIsInstance(chunk_dict, dict)
        self.assertIn("content", chunk_dict)
        self.assertIn("start_line", chunk_dict)
        self.assertIn("end_line", chunk_dict)
        self.assertIn("timestamp", chunk_dict)
        self.assertIn("log_level", chunk_dict)
        self.assertIn("service", chunk_dict)
        self.assertIn("chunk_id", chunk_dict)

    def test_chunk_logs_with_custom_size(self):
        """Test chunking with custom chunk_size and overlap."""
        test_file = os.path.join(self.temp_dir, "test.log")
        # Use smaller min_chunk_size for this test
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        chunks = chunk_logs(test_file, chunk_size=50, overlap=5, min_chunk_size=10)

        self.assertGreater(len(chunks), 0)
        for chunk in chunks:
            self.assertIsInstance(chunk, Chunk)
            # Verify chunk has content
            self.assertGreater(len(chunk.content), 0)

    def test_chunk_logs_empty_file(self):
        """Test chunking an empty file returns empty list."""
        test_file = os.path.join(self.temp_dir, "empty.log")
        with open(test_file, "w") as f:
            f.write("")

        chunks = chunk_logs(test_file)

        self.assertEqual(len(chunks), 0)
        self.assertIsInstance(chunks, list)

    def test_chunk_logs_nonexistent_file(self):
        """Test chunking a non-existent file returns empty list."""
        nonexistent_file = os.path.join(self.temp_dir, "nonexistent.log")

        chunks = chunk_logs(nonexistent_file)

        self.assertEqual(len(chunks), 0)
        self.assertIsInstance(chunks, list)

    def test_chunk_metadata_extraction(self):
        """Test that metadata (timestamp, log_level, service) is extracted."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        chunks = chunk_logs(test_file)

        self.assertGreater(len(chunks), 0)
        # At least one chunk should have metadata
        has_metadata = any(
            chunk.timestamp or chunk.log_level or chunk.service
            for chunk in chunks
        )
        self.assertTrue(has_metadata, "At least one chunk should have extracted metadata")


if __name__ == "__main__":
    unittest.main()
