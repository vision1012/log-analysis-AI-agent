import unittest
import os
import tempfile
import shutil
from utilities.search_on_keyword import search_keyword, run_search_keyword


class TestSearchKeyword(unittest.TestCase):
    """Unit tests for the search_keyword function."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.temp_files = []
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temporary files after each test method."""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        # Clean up temp directory
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass
    
    def _create_temp_log_file(self, content):
        """Helper to create a temporary log file."""
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', 
            delete=False, 
            encoding='utf-8',
            suffix='.log',
            dir=self.temp_dir
        )
        temp_file.write(content)
        temp_file.close()
        self.temp_files.append(temp_file.name)
        return temp_file.name

    def test_single_keyword_string_log_content(self):
        """Test searching with a single keyword in string log content."""
        log_content = "Error: Connection failed\nInfo: System started\nError: Timeout occurred\nDebug: Processing data"
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Error: Connection failed", content)
            self.assertIn("Error: Timeout occurred", content)
            self.assertNotIn("Info: System started", content)
            self.assertNotIn("Debug: Processing data", content)

    def test_single_keyword_list_log_content(self):
        """Test searching with a single keyword in list log content."""
        log_content = [
            "Error: Connection failed",
            "Info: System started",
            "Error: Timeout occurred",
            "Debug: Processing data"
        ]
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("Error: Connection failed", lines)
            self.assertIn("Error: Timeout occurred", lines)

    def test_multiple_keywords_string(self):
        """Test searching with multiple keywords."""
        log_content = "Error: Connection failed\nWarning: Low memory\nInfo: System started\nError: Timeout occurred"
        keywords = ["Error", "Warning"]
        
        result_file = search_keyword(log_content, keywords)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Error: Connection failed", content)
            self.assertIn("Warning: Low memory", content)
            self.assertIn("Error: Timeout occurred", content)
            self.assertNotIn("Info: System started", content)

    def test_multiple_keywords_list(self):
        """Test searching with multiple keywords in list format."""
        log_content = [
            "Error: Connection failed",
            "Warning: Low memory",
            "Info: System started",
            "Error: Timeout occurred"
        ]
        keywords = ["Error", "Warning"]
        
        result_file = search_keyword(log_content, keywords)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("Error: Connection failed", lines)
            self.assertIn("Warning: Low memory", lines)
            self.assertIn("Error: Timeout occurred", lines)

    def test_case_insensitive_matching(self):
        """Test that keyword matching is case-insensitive."""
        log_content = "ERROR: Connection failed\nerror: Timeout occurred\nError: Another error\nInfo: Normal operation"
        keyword = "error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("ERROR: Connection failed", lines)
            self.assertIn("error: Timeout occurred", lines)
            self.assertIn("Error: Another error", lines)

    def test_no_matches_found(self):
        """Test behavior when no matches are found."""
        log_content = "Info: System started\nDebug: Processing data\nWarning: Low memory"
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertEqual(content, "")

    def test_empty_log_content(self):
        """Test behavior with empty log content."""
        log_content = ""
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertEqual(content, "")

    def test_empty_list_log_content(self):
        """Test behavior with empty list log content."""
        log_content = []
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertEqual(content, "")

    def test_partial_word_matching(self):
        """Test that partial word matches are found."""
        log_content = "Error occurred\nNoError found\nErrorHandler initialized"
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("Error occurred", lines)
            self.assertIn("NoError found", lines)
            self.assertIn("ErrorHandler initialized", lines)

    def test_keyword_in_middle_of_line(self):
        """Test matching when keyword appears in the middle of a line."""
        log_content = "Processing Error: Connection timeout during operation"
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Processing Error: Connection timeout during operation", content)

    def test_multiple_keywords_case_variations(self):
        """Test multiple keywords with different case variations."""
        log_content = "ERROR: System failure\nwarning: Low resources\nInfo: Normal\nError: Another issue"
        keywords = ["error", "WARNING"]
        
        result_file = search_keyword(log_content, keywords)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("ERROR: System failure", lines)
            self.assertIn("warning: Low resources", lines)
            self.assertIn("Error: Another issue", lines)

    def test_numeric_keywords(self):
        """Test searching with numeric keywords."""
        log_content = "Process 123 started\nProcess 456 completed\nProcess 789 failed"
        keyword = "123"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Process 123 started", content)
            self.assertNotIn("Process 456 completed", content)

    def test_keyword_list_with_numeric_values(self):
        """Test keyword list containing numeric values."""
        log_content = "Error 404: Not found\nError 500: Server error\nInfo: Success"
        keywords = ["404", "500"]
        
        result_file = search_keyword(log_content, keywords)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("Error 404: Not found", lines)
            self.assertIn("Error 500: Server error", lines)

    def test_temp_file_extension(self):
        """Test that the temporary file has the correct .log extension."""
        log_content = "Error: Test message"
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(result_file.endswith('.log'))
        self.assertTrue(os.path.exists(result_file))

    def test_multiline_log_content(self):
        """Test with multiline log content."""
        log_content = """Error: First error
Info: Some info
Error: Second error
Debug: Debug message
Error: Third error"""
        keyword = "Error"
        
        result_file = search_keyword(log_content, keyword)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        with open(result_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 3)
            self.assertIn("Error: First error", lines)
            self.assertIn("Error: Second error", lines)
            self.assertIn("Error: Third error", lines)

    # ========== run_search_keyword() Function Tests ==========
    
    def test_run_search_keyword_success(self):
        """Test run_search_keyword() returns correct dictionary structure on success."""
        log_content = "Error: Connection failed\nInfo: System started\nError: Timeout occurred"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, "Error", output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 2)
        self.assertEqual(len(result["data"]["items"]), 2)
        self.assertTrue(len(result["artifacts"]) > 0)
        self.assertTrue(os.path.exists(result["artifacts"][0]["path"]))
        self.assertIn("Error", result["input"]["keywords"])
        self.assertEqual(len(result["errors"]), 0)
    
    def test_run_search_keyword_file_not_found(self):
        """Test run_search_keyword() handles file not found error."""
        result = run_search_keyword("nonexistent_file.log", "Error")
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("File not found", result["errors"][0])
        self.assertEqual(len(result["artifacts"]), 0)
    
    def test_run_search_keyword_no_keywords(self):
        """Test run_search_keyword() handles empty keywords."""
        log_content = "Error: Connection failed"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, [])
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("No keywords provided", result["errors"][0])
    
    def test_run_search_keyword_multiple_keywords(self):
        """Test run_search_keyword() with multiple keywords."""
        log_content = "Error: Connection failed\nWarning: Low memory\nInfo: System started"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, ["Error", "Warning"], output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 2)
        self.assertEqual(len(result["input"]["keywords"]), 2)
        self.assertIn("Error", result["input"]["keywords"])
        self.assertIn("Warning", result["input"]["keywords"])
    
    def test_run_search_keyword_case_sensitive(self):
        """Test run_search_keyword() with case-sensitive search."""
        log_content = "Error: Connection failed\nerror: lowercase error"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, "Error", case_sensitive=True, output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 1)  # Only "Error" matches, not "error"
    
    def test_run_search_keyword_case_insensitive(self):
        """Test run_search_keyword() with case-insensitive search."""
        log_content = "Error: Connection failed\nerror: lowercase error"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, "Error", case_sensitive=False, output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 2)  # Both match
    
    def test_run_search_keyword_no_write_file(self):
        """Test run_search_keyword() with write_file=False."""
        log_content = "Error: Connection failed"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, "Error", write_file=False)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 1)
        self.assertEqual(len(result["artifacts"]), 0)  # No file created
        self.assertEqual(len(result["data"]["items"]), 1)
    
    def test_run_search_keyword_custom_output_dir(self):
        """Test run_search_keyword() with custom output directory."""
        log_content = "Error: Connection failed"
        temp_file = self._create_temp_log_file(log_content)
        custom_output_dir = os.path.join(self.temp_dir, "custom_output")
        
        result = run_search_keyword(temp_file, "Error", output_dir=custom_output_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertTrue(len(result["artifacts"]) > 0)
        self.assertTrue(result["artifacts"][0]["path"].startswith(custom_output_dir))
        self.assertTrue(os.path.exists(custom_output_dir))
    
    def test_run_search_keyword_no_matches(self):
        """Test run_search_keyword() when no matches found."""
        log_content = "Info: System started\nDebug: Processing data"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_search_keyword(temp_file, "Error", output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["summary"]["key_metrics"]["match_count"], 0)
        self.assertEqual(len(result["data"]["items"]), 0)
        # File should still be created even with no matches
        self.assertTrue(len(result["artifacts"]) > 0)


if __name__ == '__main__':
    unittest.main()

