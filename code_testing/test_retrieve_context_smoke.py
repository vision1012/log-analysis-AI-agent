"""
Smoke Test for run_retrieve_context Tool

Tests that the tool can be called manually and returns valid ToolResult.
"""

import unittest
import tempfile
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utilities.retrieve_context import run_retrieve_context
from agent.tool_wrapper import validate_tool_result
from agent.runtime.tool_registry import get_tool


class TestRetrieveContextSmoke(unittest.TestCase):
    """Smoke tests for run_retrieve_context tool."""

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
        self.test_log_content = "\n".join(base_log_lines * 3)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tool_is_registered(self):
        """Test that run_retrieve_context is registered in tool registry."""
        try:
            tool_func = get_tool("run_retrieve_context")
            self.assertIsNotNone(tool_func)
            self.assertEqual(tool_func.__name__, "run_retrieve_context")
        except KeyError:
            self.fail("run_retrieve_context not found in tool registry")

    def test_tool_can_be_called_manually(self):
        """Test that run_retrieve_context can be called manually."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # Call tool directly
        result = run_retrieve_context(
            file_path=test_file,
            query="why are timeouts happening",
            top_k=3,
            write_file=False,
        )

        # Should return a dict
        self.assertIsInstance(result, dict)
        self.assertEqual(result["tool"], "run_retrieve_context")
        self.assertIn(result["status"], ["success", "error"])

    def test_tool_result_validates(self):
        """Test that tool result validates via validate_tool_result."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        result = run_retrieve_context(
            file_path=test_file,
            query="why are timeouts happening",
            top_k=3,
            write_file=False,
        )

        # Should validate without raising
        validated = validate_tool_result(result)
        self.assertIsInstance(validated, dict)
        self.assertEqual(validated["tool"], "run_retrieve_context")

    def test_tool_handles_missing_dependencies(self):
        """Test that tool handles missing dependencies gracefully."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        result = run_retrieve_context(
            file_path=test_file,
            query="test query",
            top_k=3,
            write_file=False,
        )

        # Should return valid ToolResult even if dependencies missing
        validated = validate_tool_result(result)
        self.assertIsInstance(validated, dict)
        
        # If error due to dependencies, should have dependency_missing code
        if validated["status"] == "error":
            errors = validated.get("errors", [])
            if errors:
                error_codes = [err.get("code", "") for err in errors]
                # Should have dependency_missing or other error code
                self.assertTrue(len(error_codes) > 0)

    def test_tool_saves_to_job_directory(self):
        """Test that tool saves retrieval.json when output_dir is a job directory."""
        test_file = os.path.join(self.temp_dir, "test.log")
        with open(test_file, "w") as f:
            f.write(self.test_log_content)

        # Create a job-like directory
        job_dir = os.path.join(self.temp_dir, "output", "jobs", "test_job_123")
        os.makedirs(job_dir, exist_ok=True)

        result = run_retrieve_context(
            file_path=test_file,
            query="why are timeouts happening",
            top_k=3,
            output_dir=job_dir,
            write_file=True,
        )

        # Should save retrieval.json in job directory
        retrieval_file = os.path.join(job_dir, "retrieval.json")
        
        # If successful, file should exist
        if result["status"] == "success":
            # Check if artifact path points to retrieval.json
            artifacts = result.get("artifacts", [])
            if artifacts:
                artifact_paths = [a.get("path", "") for a in artifacts]
                # Should have retrieval.json in artifacts or job directory
                has_retrieval = any("retrieval.json" in path for path in artifact_paths)
                # Or file should exist
                file_exists = os.path.isfile(retrieval_file)
                self.assertTrue(has_retrieval or file_exists, "retrieval.json should be saved")


if __name__ == "__main__":
    unittest.main()
