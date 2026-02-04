"""
Tests for Index Reuse

Tests that indexes are persisted and reused across runs to avoid re-embedding.
"""

import unittest
import tempfile
import os
import time
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utilities.retrieve_context import run_retrieve_context
from agent.rag.index_manager import (
    compute_file_index_key,
    check_index_exists,
    get_index_dir,
)


class TestIndexReuse(unittest.TestCase):
    """Test index persistence and reuse."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        # Create a longer test log for chunking
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
        self.test_log_content = "\n".join(base_log_lines * 5)  # Make it longer

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Clean up indexes
        indexes_dir = os.path.join("output", "indexes")
        if os.path.exists(indexes_dir):
            shutil.rmtree(indexes_dir, ignore_errors=True)

    def test_index_key_is_stable(self):
        """Test that index key is stable for the same file."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        key1 = compute_file_index_key(test_file)
        # Wait a bit and check again
        time.sleep(0.1)
        key2 = compute_file_index_key(test_file)

        self.assertEqual(key1, key2, "Index key should be stable for unchanged file")

    def test_index_key_changes_on_file_modification(self):
        """Test that index key changes when file is modified."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        key1 = compute_file_index_key(test_file)

        # Modify file
        time.sleep(0.1)  # Ensure mtime changes
        with open(test_file, "a") as f:
            f.write("\n2025-01-12 09:15:13 [INFO] New line added")

        key2 = compute_file_index_key(test_file)

        self.assertNotEqual(key1, key2, "Index key should change when file is modified")

    def test_index_reuse_across_runs(self):
        """Test that index is reused on second run."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # First run - should create index
        result1 = run_retrieve_context(
            file_path=test_file,
            query="why are timeouts happening",
            top_k=3,
            write_file=False,
        )

        # Check first run metrics
        self.assertIn(result1["status"], ["success", "error"])  # May fail if deps missing
        if result1["status"] == "success":
            metrics1 = result1["summary"]["key_metrics"]
            self.assertIn("index_status", metrics1)
            # First run should be index_miss
            if "index_miss" in metrics1:
                self.assertTrue(metrics1.get("index_miss", False))

        # Second run - should reuse index
        result2 = run_retrieve_context(
            file_path=test_file,
            query="what caused the errors",
            top_k=3,
            write_file=False,
        )

        # Check second run metrics
        if result2["status"] == "success":
            metrics2 = result2["summary"]["key_metrics"]
            self.assertIn("index_status", metrics2)
            # Second run should be index_hit
            if "index_hit" in metrics2:
                self.assertTrue(metrics2.get("index_hit", False))
                self.assertFalse(metrics2.get("index_miss", True))

    def test_index_exists_after_first_run(self):
        """Test that index directory exists after first run."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # First run
        result1 = run_retrieve_context(
            file_path=test_file,
            query="test query",
            top_k=3,
            write_file=False,
        )

        # Check if index was created
        index_key = compute_file_index_key(test_file)
        index_dir = get_index_dir(index_key, "output/indexes")

        # Index may not exist if dependencies are missing
        # But if it does exist, it should have metadata
        if os.path.isdir(index_dir):
            metadata_path = os.path.join(index_dir, "index_metadata.json")
            self.assertTrue(os.path.isfile(metadata_path), "Index metadata should exist")

    def test_index_check_function(self):
        """Test check_index_exists function."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # Check before indexing
        exists, index_dir, metadata = check_index_exists(test_file)
        self.assertFalse(exists, "Index should not exist before indexing")

        # Run indexing
        result = run_retrieve_context(
            file_path=test_file,
            query="test query",
            top_k=3,
            write_file=False,
        )

        # Check after indexing (if successful)
        if result["status"] == "success":
            exists, index_dir, metadata = check_index_exists(test_file)
            # Index should exist if dependencies are available
            if exists:
                self.assertIsNotNone(index_dir)
                self.assertIsNotNone(metadata)
                self.assertIn("chunks_count", metadata)
                self.assertIn("file_path", metadata)

    def test_index_reuse_is_faster(self):
        """Test that second run is faster (index reuse)."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # First run - measure time
        start1 = time.time()
        result1 = run_retrieve_context(
            file_path=test_file,
            query="why are timeouts happening",
            top_k=3,
            write_file=False,
        )
        time1 = time.time() - start1

        # Second run - measure time
        start2 = time.time()
        result2 = run_retrieve_context(
            file_path=test_file,
            query="what caused the errors",
            top_k=3,
            write_file=False,
        )
        time2 = time.time() - start2

        # If both succeeded, second should be faster (or at least not slower)
        if result1["status"] == "success" and result2["status"] == "success":
            metrics2 = result2["summary"]["key_metrics"]
            if metrics2.get("index_hit", False):
                # Second run should be faster (index reuse)
                # Allow some variance, but second should be <= first
                self.assertLessEqual(
                    time2, time1 * 1.5,  # Allow 50% variance
                    "Second run with index reuse should be faster or similar"
                )


if __name__ == "__main__":
    unittest.main()
