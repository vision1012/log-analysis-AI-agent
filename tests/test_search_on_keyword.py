import unittest
import os
from utilities.search_on_keyword import search_keyword


class TestSearchKeyword(unittest.TestCase):
    """Unit tests for the search_keyword function."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.temp_files = []

    def tearDown(self):
        """Clean up temporary files after each test method."""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

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


if __name__ == '__main__':
    unittest.main()

