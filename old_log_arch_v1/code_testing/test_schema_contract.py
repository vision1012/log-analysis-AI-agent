"""
Schema Contract Tests

These tests ensure all run_*() functions return data that validates
against the Pydantic ToolResult schema. This prevents schema drift
and ensures the agent can reliably consume tool outputs.
"""

import unittest
import tempfile
import os
from datetime import datetime

try:
    from agent.schemas import ToolResult
    from agent.tool_wrapper import validate_tool_result
except ImportError:
    # If pydantic not installed, skip these tests
    ToolResult = None
    validate_tool_result = None

from utilities.log_summary import run_log_summary
from utilities.filter_log_level import run_filter_log_level
from utilities.search_on_keyword import run_search_keyword
from utilities.time_slice import run_time_slice
from utilities.stacktrace import run_stacktrace
from utilities.error_lines import run_error_lines
from utilities.error_code import run_error_code_search, run_error_code_extract_all
from utilities.retrieve_context import run_retrieve_context


@unittest.skipIf(ToolResult is None, "Pydantic not installed")
class TestSchemaContract(unittest.TestCase):
    """Test that all tools return schema-compliant ToolResult."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_temp_log_file(self, content: str) -> str:
        """Create a temporary log file for testing."""
        fd, path = tempfile.mkstemp(suffix='.log', dir=self.temp_dir)
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        return path
    
    def test_run_log_summary_schema(self):
        """Test run_log_summary() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_log_summary(temp_file, write_file=False)
        
        # Validate with Pydantic
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        # Assert schema compliance
        self.assertEqual(result.tool, "run_log_summary")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
        self.assertIsInstance(result.artifacts, list)
        self.assertIsInstance(result.warnings, list)
        self.assertIsInstance(result.errors, list)
    
    def test_run_filter_log_level_schema(self):
        """Test run_filter_log_level() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_filter_log_level(temp_file, "ERROR", write_file=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_filter_log_level")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_search_keyword_schema(self):
        """Test run_search_keyword() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_search_keyword(temp_file, "Error", write_file=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_search_keyword")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_time_slice_schema(self):
        """Test run_time_slice() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [INFO] Test log"
        temp_file = self._create_temp_log_file(log_content)
        
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = datetime(2024, 1, 1, 11, 0, 0)
        
        raw = run_time_slice(temp_file, start_time, end_time, write_file=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_time_slice")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_stacktrace_schema(self):
        """Test run_stacktrace() returns valid ToolResult schema."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Exception occurred\n"
            "java.lang.NullPointerException: null pointer\n"
            "    at com.example.Test.method(Test.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_stacktrace(temp_file, write_file=False, min_stack_depth=1)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_stacktrace")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_error_lines_schema(self):
        """Test run_error_lines() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_error_lines(temp_file, write_file=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_error_lines")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_error_code_search_schema(self):
        """Test run_error_code_search() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error code: ERR500"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_error_code_search(temp_file, "ERR500", write_file=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_error_code_search")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_run_error_code_extract_all_schema(self):
        """Test run_error_code_extract_all() returns valid ToolResult schema."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error code: ERR500"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_error_code_extract_all(temp_file, write_summary=False)
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_error_code_extract_all")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
    
    def test_schema_extra_fields_forbidden(self):
        """Test that extra fields are rejected (extra='forbid')."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message"
        temp_file = self._create_temp_log_file(log_content)
        
        raw = run_log_summary(temp_file, write_file=False)
        
        # Add an extra field that shouldn't be allowed
        raw["extra_field"] = "should be rejected"
        
        # Validation should normalize it, but Pydantic should reject extra fields
        with self.assertRaises(Exception):
            ToolResult.model_validate(raw)
    
    def test_run_retrieve_context_schema(self):
        """Test run_retrieve_context() returns valid ToolResult schema."""
        log_content = """2025-01-12 09:15:02 [INFO] AuthService - User login initiated user=jay
2025-01-12 09:15:03 [DEBUG] AuthService - Validating credentials
2025-01-12 09:15:04 [WARN] InventoryService - Stock low for SKU=1223
2025-01-12 09:15:05 [ERROR] DBService - CRJAZ1282E Database connection failure
2025-01-12 09:15:05     at com.db.Driver.connect(Driver.java:88)
2025-01-12 09:15:05     at com.db.ConnectionPool.getConnection(ConnectionPool.java:130)
2025-01-12 09:15:06 [DEBUG] DBService - Retrying connection attempt 1
2025-01-12 09:15:07 [ERROR] DBService - CRJAZ1282E Timeout after 5000ms
2025-01-12 09:15:08 [INFO] NotificationService - Email sent user=jay
2025-01-12 09:15:09 [INFO] ReportService - Generating weekly report
2025-01-12 09:15:10 [ERROR] ReportService - RPT9002E Report generation timeout
2025-01-12 09:15:10     at com.report.Builder.generate(Builder.java:210)
2025-01-12 09:15:11 [DEBUG] System - Running cron cleanup
2025-01-12 09:15:12 [INFO] System - Cleanup completed
""" * 3  # Make it longer for chunking
        temp_file = self._create_temp_log_file(log_content)
        
        # Test with write_file=False to avoid file I/O in tests
        raw = run_retrieve_context(
            temp_file,
            "why are timeouts happening",
            top_k=5,
            write_file=False
        )
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_retrieve_context")
        self.assertIn(result.status, ["success", "error"])
        self.assertIsNotNone(result.input)
        self.assertIsNotNone(result.summary)
        self.assertIsNotNone(result.data)
        
        # If successful, should have items in data
        if result.status == "success":
            self.assertIsInstance(result.data.items, list)
    
    def test_run_retrieve_context_missing_dependencies(self):
        """Test run_retrieve_context() handles missing dependencies gracefully."""
        log_content = "2025-01-12 09:15:02 [INFO] Test log line"
        temp_file = self._create_temp_log_file(log_content)
        
        # This test will pass if dependencies are missing (returns error ToolResult)
        # or succeed if dependencies are present
        raw = run_retrieve_context(
            temp_file,
            "test query",
            top_k=5,
            write_file=False
        )
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        self.assertEqual(result.tool, "run_retrieve_context")
        self.assertIn(result.status, ["success", "error"])
        
        # If error due to missing dependencies, check error code
        if result.status == "error" and result.errors:
            error_codes = [err.code for err in result.errors]
            # Should have dependency_missing or other error code
            self.assertTrue(len(error_codes) > 0)
    
    def test_validate_tool_result_normalizes_errors(self):
        """Test that validate_tool_result normalizes string errors to ToolError format."""
        raw = {
            "tool": "test_tool",
            "status": "error",
            "input": {"file_path": "test.log", "options": {}},
            "summary": {"headline": "Test", "key_metrics": {}},
            "data": {"items": [], "text": None, "json": {}},
            "artifacts": [],
            "warnings": [],
            "errors": ["String error"]  # String instead of dict
        }
        
        validated = validate_tool_result(raw)
        result = ToolResult.model_validate(validated)
        
        # Errors should be normalized to ToolError format
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].code, "error")
        self.assertEqual(result.errors[0].message, "String error")


if __name__ == '__main__':
    unittest.main()
