"""
Artifact Paths Contract Tests

These tests enforce Step 6 rules:
- All artifacts must be under output/jobs/<job_id>/
- No files should be created directly under root output/ during job execution
- Tools cannot escape the job directory
- Job directory structure is created correctly
"""

import unittest
import tempfile
import os
import shutil
import json
from pathlib import Path

from agent.runtime.worker import run_job
from agent.runtime.job_models import JobRequest


class TestArtifactPathsContract(unittest.TestCase):
    """Test that artifact paths conform to Step 6 rules."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for test output
        self.test_output_base = tempfile.mkdtemp(prefix="test_output_")
        # Override the default output/jobs path for testing
        self.original_cwd = os.getcwd()
        
        # Create test log file
        self.temp_dir = tempfile.mkdtemp()
        self.test_log_file = os.path.join(self.temp_dir, "test.log")
        with open(self.test_log_file, "w") as f:
            f.write("""2025-01-12 09:15:02 [INFO] TestService - Application started
2025-01-12 09:15:05 [ERROR] TestService - CRJAZ1282E Database connection failure
2025-01-12 09:15:07 [WARN] TestService - Connection retry attempt 1
2025-01-12 09:15:10 [ERROR] TestService - RPT9002E Report generation timeout
""")
    
    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up test output directory
        if os.path.exists(self.test_output_base):
            shutil.rmtree(self.test_output_base, ignore_errors=True)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        # Clean up any output/jobs directories created during tests
        output_jobs = os.path.join(self.original_cwd, "output", "jobs")
        if os.path.exists(output_jobs):
            for job_dir in os.listdir(output_jobs):
                job_path = os.path.join(output_jobs, job_dir)
                if os.path.isdir(job_path) and job_dir.startswith("test_"):
                    shutil.rmtree(job_path, ignore_errors=True)
    
    def _get_output_jobs_dir(self):
        """Get the output/jobs directory path."""
        return os.path.join(self.original_cwd, "output", "jobs")
    
    def _list_files_in_output_root(self):
        """List all files directly under output/ (excluding output/jobs/)."""
        output_dir = os.path.join(self.original_cwd, "output")
        if not os.path.exists(output_dir):
            return []
        
        files = []
        for item in os.listdir(output_dir):
            item_path = os.path.join(output_dir, item)
            # Skip output/jobs/ directory
            if item == "jobs":
                continue
            if os.path.isfile(item_path):
                files.append(item_path)
        return files
    
    def _get_job_directories(self):
        """Get all job directories created during test."""
        jobs_dir = self._get_output_jobs_dir()
        if not os.path.exists(jobs_dir):
            return []
        
        job_dirs = []
        for item in os.listdir(jobs_dir):
            item_path = os.path.join(jobs_dir, item)
            if os.path.isdir(item_path):
                job_dirs.append(item_path)
        return job_dirs
    
    def test_job_creates_correct_directory_structure(self):
        """Test that running a job creates the correct directory structure."""
        # Get initial state
        initial_files = set(self._list_files_in_output_root())
        initial_job_dirs = set(self._get_job_directories())
        
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        # Verify job was created
        self.assertIsNotNone(result.job_id)
        self.assertIn(result.status, ["succeeded", "failed"])
        
        # Verify job directory exists
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        self.assertTrue(os.path.exists(job_dir), f"Job directory should exist: {job_dir}")
        
        # Verify job.json exists
        job_json = os.path.join(job_dir, "job.json")
        self.assertTrue(os.path.exists(job_json), f"job.json should exist: {job_json}")
        
        # Verify artifacts directory exists
        artifacts_dir = os.path.join(job_dir, "artifacts")
        self.assertTrue(os.path.exists(artifacts_dir), f"artifacts directory should exist: {artifacts_dir}")
        
        # Verify inputs directory exists
        inputs_dir = os.path.join(job_dir, "inputs")
        self.assertTrue(os.path.exists(inputs_dir), f"inputs directory should exist: {inputs_dir}")
        
        # Verify tool_results directory exists
        tool_results_dir = os.path.join(job_dir, "tool_results")
        self.assertTrue(os.path.exists(tool_results_dir), f"tool_results directory should exist: {tool_results_dir}")
    
    def test_all_artifact_paths_under_job_directory(self):
        """Test that all artifact paths are under output/jobs/<job_id>/."""
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        job_dir_abs = os.path.abspath(job_dir)
        
        # Check all artifacts in tool_results
        for tool_result in result.tool_results:
            artifacts = tool_result.get("artifacts", [])
            for artifact in artifacts:
                artifact_path = artifact.get("path", "")
                if artifact_path:
                    artifact_abs = os.path.abspath(artifact_path)
                    # Normalize paths for comparison
                    job_dir_normalized = os.path.normpath(job_dir_abs) + os.sep
                    artifact_normalized = os.path.normpath(artifact_abs)
                    
                    self.assertTrue(
                        artifact_normalized.startswith(job_dir_normalized) or artifact_normalized == job_dir_abs,
                        f"Artifact path '{artifact_path}' (abs: '{artifact_abs}') must be under job directory '{job_dir_abs}'"
                    )
        
        # Check all artifacts in JobResult
        for artifact_ref in result.artifacts:
            artifact_path = artifact_ref.path
            if artifact_path:
                artifact_abs = os.path.abspath(artifact_path)
                job_dir_normalized = os.path.normpath(job_dir_abs) + os.sep
                artifact_normalized = os.path.normpath(artifact_abs)
                
                self.assertTrue(
                    artifact_normalized.startswith(job_dir_normalized) or artifact_normalized == job_dir_abs,
                    f"ArtifactRef path '{artifact_path}' (abs: '{artifact_abs}') must be under job directory '{job_dir_abs}'"
                )
    
    def test_no_files_created_in_root_output(self):
        """Test that no files are created directly under root output/ during job execution."""
        # Get initial files in output root
        initial_files = set(self._list_files_in_output_root())
        
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        # Get files after job execution
        final_files = set(self._list_files_in_output_root())
        
        # Verify no new files were created in root output/
        new_files = final_files - initial_files
        self.assertEqual(
            len(new_files), 0,
            f"No files should be created in root output/ directory. New files: {new_files}"
        )
    
    def test_tool_results_persisted_under_job_directory(self):
        """Test that tool result JSON files are persisted under job directory."""
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        tool_results_dir = os.path.join(job_dir, "tool_results")
        
        # Verify tool_results directory exists
        self.assertTrue(os.path.exists(tool_results_dir))
        
        # Verify tool result files exist
        tool_result_files = [f for f in os.listdir(tool_results_dir) if f.endswith(".json")]
        self.assertGreater(
            len(tool_result_files), 0,
            "At least one tool result file should be persisted"
        )
        
        # Verify each tool result file is valid JSON and contains ToolResult
        for tool_result_file in tool_result_files:
            file_path = os.path.join(tool_results_dir, tool_result_file)
            self.assertTrue(
                file_path.startswith(job_dir),
                f"Tool result file '{file_path}' must be under job directory '{job_dir}'"
            )
            
            # Verify it's valid JSON
            with open(file_path, "r") as f:
                tool_result_data = json.load(f)
            
            # Verify it has required ToolResult fields
            self.assertIn("tool", tool_result_data)
            self.assertIn("status", tool_result_data)
            self.assertIn("input", tool_result_data)
    
    def test_job_json_contains_correct_structure(self):
        """Test that job.json contains the correct structure and all required fields."""
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        job_json = os.path.join(job_dir, "job.json")
        
        # Load job.json
        with open(job_json, "r") as f:
            job_data = json.load(f)
        
        # Verify required fields
        self.assertIn("job_id", job_data)
        self.assertIn("status", job_data)
        self.assertIn("tool_calls", job_data)
        self.assertIn("tool_results", job_data)
        self.assertIn("artifacts", job_data)
        self.assertIn("warnings", job_data)
        self.assertIn("errors", job_data)
        self.assertIn("timing", job_data)
        
        # Verify job_id matches
        self.assertEqual(job_data["job_id"], result.job_id)
        
        # Verify tool_results match
        self.assertEqual(len(job_data["tool_results"]), len(result.tool_results))
    
    def test_multiple_tools_all_artifacts_under_job_directory(self):
        """Test that when multiple tools are called, all artifacts are under job directory."""
        # Run a job that triggers multiple tools
        request = JobRequest(
            query="Summarize errors and extract stacktraces",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        job_dir_abs = os.path.abspath(job_dir)
        job_dir_normalized = os.path.normpath(job_dir_abs) + os.sep
        
        # Collect all artifact paths
        all_artifact_paths = []
        
        # From tool_results
        for tool_result in result.tool_results:
            for artifact in tool_result.get("artifacts", []):
                path = artifact.get("path", "")
                if path:
                    all_artifact_paths.append(path)
        
        # From JobResult artifacts
        for artifact_ref in result.artifacts:
            if artifact_ref.path:
                all_artifact_paths.append(artifact_ref.path)
        
        # Verify all paths are under job directory
        for artifact_path in all_artifact_paths:
            artifact_abs = os.path.abspath(artifact_path)
            artifact_normalized = os.path.normpath(artifact_abs)
            
            self.assertTrue(
                artifact_normalized.startswith(job_dir_normalized) or artifact_normalized == job_dir_abs,
                f"All artifacts must be under job directory. Found: '{artifact_path}' (abs: '{artifact_abs}')"
            )
    
    def test_input_files_copied_to_job_directory(self):
        """Test that input files are copied to job directory inputs/ folder."""
        # Run a job
        request = JobRequest(
            query="Summarize errors",
            file_paths=[self.test_log_file],
        )
        result = run_job(request, mode="heuristic")
        
        job_dir = os.path.join(self._get_output_jobs_dir(), result.job_id)
        inputs_dir = os.path.join(job_dir, "inputs")
        
        # Verify inputs directory exists
        self.assertTrue(os.path.exists(inputs_dir))
        
        # Verify input file was copied
        input_files = os.listdir(inputs_dir)
        self.assertGreater(len(input_files), 0, "Input file should be copied to inputs/ directory")
        
        # Verify copied file exists and is readable
        copied_file = os.path.join(inputs_dir, os.path.basename(self.test_log_file))
        self.assertTrue(os.path.exists(copied_file), f"Copied input file should exist: {copied_file}")


if __name__ == "__main__":
    unittest.main()
