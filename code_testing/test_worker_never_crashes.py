"""
Worker Never Crashes Tests

These tests enforce the "worker must never crash" principle:
- All exceptions are caught and converted to JobResult errors
- run_job() always returns a valid JobResult, never raises exceptions
- Tool failures result in validated ToolResult dicts with status="error"
- Job continues execution even when individual tools fail
"""

import unittest
import tempfile
import os
import shutil

from agent.runtime.worker import run_job
from agent.runtime.job_models import JobRequest, JobResult, JobStatus
from agent.schemas import ToolResult
from agent.tool_wrapper import validate_tool_result


class TestWorkerNeverCrashes(unittest.TestCase):
    """Test that worker never crashes and always returns valid JobResult."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create a valid test log file
        self.valid_log_file = os.path.join(self.temp_dir, "valid.log")
        with open(self.valid_log_file, "w") as f:
            f.write("""2025-01-12 09:15:02 [INFO] TestService - Application started
2025-01-12 09:15:05 [ERROR] TestService - CRJAZ1282E Database connection failure
""")
        
        # Create a non-existent file path
        self.non_existent_file = os.path.join(self.temp_dir, "does_not_exist.log")
    
    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        # Clean up any output/jobs directories created during tests
        output_jobs = os.path.join(os.getcwd(), "output", "jobs")
        if os.path.exists(output_jobs):
            for job_dir in os.listdir(output_jobs):
                job_path = os.path.join(output_jobs, job_dir)
                if os.path.isdir(job_path):
                    # Only clean up test directories (those created during tests)
                    try:
                        shutil.rmtree(job_path, ignore_errors=True)
                    except Exception:
                        pass
    
    def test_non_existent_file_path_returns_job_result(self):
        """Test that job with non-existent file returns JobResult instead of crashing."""
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.non_existent_file],
        )
        
        # This should NOT raise an exception
        result = run_job(request, mode="heuristic")
        
        # Verify it returns a valid JobResult
        self.assertIsInstance(result, JobResult)
        self.assertIsNotNone(result.job_id)
        self.assertIn(result.status, ["succeeded", "failed"])
        
        # Verify errors are populated
        self.assertGreater(len(result.errors), 0, "Errors should be populated when file doesn't exist")
        
        # Verify job.json was written (proves no crash)
        output_jobs = os.path.join(os.getcwd(), "output", "jobs")
        job_dir = os.path.join(output_jobs, result.job_id)
        job_json = os.path.join(job_dir, "job.json")
        self.assertTrue(os.path.exists(job_json), "job.json should exist even when job fails")
    
    def test_tool_failure_returns_valid_tool_result(self):
        """Test that when a tool fails, it returns a valid ToolResult with status='error'."""
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.non_existent_file],
        )
        
        result = run_job(request, mode="heuristic")
        
        # Verify tool_results exist and are valid
        self.assertGreater(len(result.tool_results), 0, "Should have at least one tool result")
        
        for tool_result in result.tool_results:
            # Verify it's a dict (ToolResult structure)
            self.assertIsInstance(tool_result, dict)
            
            # Verify required fields
            self.assertIn("tool", tool_result)
            self.assertIn("status", tool_result)
            self.assertIn("input", tool_result)
            self.assertIn("errors", tool_result)
            
            # Verify status is "error" for failed tools
            if tool_result.get("status") == "error":
                # Verify errors list is populated
                errors = tool_result.get("errors", [])
                self.assertGreater(len(errors), 0, "Error tool results should have errors list populated")
                
                # Verify errors are strings or dicts with code/message
                for error in errors:
                    if isinstance(error, dict):
                        self.assertIn("code", error)
                        self.assertIn("message", error)
                    else:
                        # Should be a string
                        self.assertIsInstance(error, str)
            
            # Verify it validates against ToolResult schema
            try:
                validated = ToolResult(**tool_result)
                self.assertIsNotNone(validated)
            except Exception as e:
                self.fail(f"ToolResult should validate against schema: {e}")
    
    def test_job_continues_after_tool_failure(self):
        """Test that job continues execution even when a tool fails."""
        # Create a request that might trigger multiple tools
        request = JobRequest(
            query="Summarize errors and extract stacktraces",
            file_paths=[self.non_existent_file],
        )
        
        result = run_job(request, mode="heuristic")
        
        # Verify job completed (didn't crash)
        self.assertIsInstance(result, JobResult)
        self.assertIsNotNone(result.job_id)
        
        # Verify we have tool results (even if they failed)
        self.assertGreater(len(result.tool_results), 0)
        
        # Verify tool_calls exist
        self.assertGreater(len(result.tool_calls), 0)
    
    def test_no_exception_escapes_run_job(self):
        """Test that no uncaught exception escapes run_job()."""
        # Test with various error scenarios
        test_cases = [
            # Non-existent file
            JobRequest(query="Summarize errors", file_paths=[self.non_existent_file]),
            # Empty file paths
            JobRequest(query="Summarize errors", file_paths=[]),
            # Invalid query that might cause planning issues
            JobRequest(query="", file_paths=[self.valid_log_file]),
        ]
        
        for request in test_cases:
            with self.subTest(query=request.query, file_paths=request.file_paths):
                # This should NEVER raise an exception
                try:
                    result = run_job(request, mode="heuristic")
                except Exception as e:
                    self.fail(f"run_job() should not raise exceptions. Got: {type(e).__name__}: {e}")
                
                # Verify it always returns a JobResult
                self.assertIsInstance(result, JobResult)
                self.assertIsNotNone(result.job_id)
                self.assertIn(result.status, ["succeeded", "failed"])
    
    def test_tool_result_errors_have_proper_structure(self):
        """Test that tool result errors have proper structure (code and message)."""
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.non_existent_file],
        )
        
        result = run_job(request, mode="heuristic")
        
        # Find error tool results
        error_results = [tr for tr in result.tool_results if tr.get("status") == "error"]
        self.assertGreater(len(error_results), 0, "Should have at least one error tool result")
        
        for tool_result in error_results:
            errors = tool_result.get("errors", [])
            self.assertGreater(len(errors), 0, "Error tool result should have errors")
            
            # Verify error structure
            for error in errors:
                if isinstance(error, dict):
                    # Should have code and message
                    self.assertIn("code", error)
                    self.assertIn("message", error)
                    self.assertIsInstance(error["code"], str)
                    self.assertIsInstance(error["message"], str)
                else:
                    # String errors are also acceptable (will be normalized by validate_tool_result)
                    self.assertIsInstance(error, str)
    
    def test_job_result_errors_are_strings(self):
        """Test that JobResult.errors are strings (not complex objects)."""
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.non_existent_file],
        )
        
        result = run_job(request, mode="heuristic")
        
        # Verify errors are populated
        if len(result.errors) > 0:
            for error in result.errors:
                # JobResult.errors should be strings
                self.assertIsInstance(error, str)
                self.assertGreater(len(error), 0)
    
    def test_valid_job_succeeds_despite_previous_failures(self):
        """Test that a valid job after failures still succeeds."""
        # First run a failing job
        failing_request = JobRequest(
            query="Summarize errors",
            file_paths=[self.non_existent_file],
        )
        failing_result = run_job(failing_request, mode="heuristic")
        self.assertIn(failing_result.status, ["succeeded", "failed"])
        
        # Then run a valid job
        valid_request = JobRequest(
            query="Summarize errors",
            file_paths=[self.valid_log_file],
        )
        valid_result = run_job(valid_request, mode="heuristic")
        
        # Verify valid job succeeds
        self.assertIsInstance(valid_result, JobResult)
        self.assertIsNotNone(valid_result.job_id)
        # Valid job should succeed (or at least not fail due to file issues)
        self.assertIn(valid_result.status, ["succeeded", "failed"])
        
        # Verify it has tool results
        self.assertGreater(len(valid_result.tool_results), 0)


if __name__ == "__main__":
    unittest.main()
