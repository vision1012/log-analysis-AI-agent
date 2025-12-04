import unittest
import os
import tempfile
from datetime import datetime
from utilities.stacktrace import (
    extract_stacktraces,
    extract_stacktraces_to_files,
    format_stacktrace_summary,
    Stacktrace,
    StacktraceSummary,
    _is_stacktrace_header,
    _is_stacktrace_line,
    _extract_timestamp,
    _extract_log_level,
    _extract_service,
    _extract_error_code,
    _extract_exception_type,
    _normalize_signature
)


class TestStacktrace(unittest.TestCase):
    """Unit tests for the stacktrace module."""

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
        
        if os.path.exists(self.temp_dir):
            try:
                for file in os.listdir(self.temp_dir):
                    os.unlink(os.path.join(self.temp_dir, file))
                os.rmdir(self.temp_dir)
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

    # ==================== File Existence Tests ====================

    def test_file_not_found(self):
        """Test that FileNotFoundError is raised for non-existent file."""
        with self.assertRaises(FileNotFoundError):
            extract_stacktraces('nonexistent_file.log')

    def test_file_exists_and_readable(self):
        """Test that existing file is read correctly."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)"
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertIsInstance(stacktraces, list)
        self.assertIsInstance(summary, StacktraceSummary)

    # ==================== File Opening Tests ====================

    def test_file_encoding_utf8(self):
        """Test file opening with UTF-8 encoding."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error with unicode: émoji 🎉\n2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)"
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertIsInstance(stacktraces, list)

    def test_file_with_invalid_characters(self):
        """Test file opening with errors='ignore' handles invalid characters."""
        temp_file = tempfile.NamedTemporaryFile(
            mode='wb', 
            delete=False, 
            suffix='.log',
            dir=self.temp_dir
        )
        temp_file.write(b"2024-01-01 10:00:00 [ERROR] Valid line\n")
        temp_file.write(b'\xff\xfe')  # Invalid UTF-8
        temp_file.write(b"2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n")
        temp_file.close()
        self.temp_files.append(temp_file.name)
        
        stacktraces, summary = extract_stacktraces(temp_file.name)
        self.assertIsInstance(stacktraces, list)

    def test_empty_file(self):
        """Test handling of empty log file."""
        temp_file = self._create_temp_log_file("")
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 0)
        self.assertEqual(summary.total_stacktraces, 0)

    def test_file_with_only_whitespace(self):
        """Test handling of file with only whitespace."""
        temp_file = self._create_temp_log_file("   \n\t\n  \n")
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 0)

    # ==================== Stacktrace Detection Tests ====================

    def test_stacktrace_detection_with_error_header(self):
        """Test detection of stacktrace with ERROR header."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - CRJAZ1282E Database error\n"
            "2024-01-01 10:00:00     at com.db.Driver.connect(Driver.java:88)\n"
            "2024-01-01 10:00:00     at com.db.ConnectionPool.get(ConnectionPool.java:120)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].log_level, 'ERROR')

    def test_stacktrace_detection_with_fatal_header(self):
        """Test detection of stacktrace with FATAL header."""
        log_content = (
            "2024-01-01 10:00:00 [FATAL] Critical failure\n"
            "2024-01-01 10:00:00     at com.app.Main.start(Main.java:50)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].log_level, 'FATAL')

    def test_stacktrace_detection_with_exception_in_header(self):
        """Test detection when exception name is in header."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] NullPointerException thrown\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertIn('NullPointerException', stacktraces[0].exception_type)

    def test_no_stacktraces_in_log(self):
        """Test handling of log with no stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info message\n"
            "2024-01-01 10:01:00 [DEBUG] Debug message\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 0)
        self.assertEqual(summary.total_stacktraces, 0)

    def test_multiple_stacktraces(self):
        """Test detection of multiple stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 2)
        self.assertEqual(summary.total_stacktraces, 2)

    # ==================== Context Lines Tests ====================

    def test_context_lines_capture(self):
        """Test that context lines before stacktrace are captured."""
        log_content = (
            "2024-01-01 09:59:00 [INFO] Line 1\n"
            "2024-01-01 09:59:30 [INFO] Line 2\n"
            "2024-01-01 09:59:45 [WARN] Line 3\n"
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file, include_context_lines=3)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreaterEqual(len(stacktraces[0].context_before), 3)

    def test_context_lines_default(self):
        """Test that default context lines (4) are captured."""
        log_content = (
            "2024-01-01 09:59:00 [INFO] Line 1\n"
            "2024-01-01 09:59:30 [INFO] Line 2\n"
            "2024-01-01 09:59:45 [WARN] Line 3\n"
            "2024-01-01 09:59:50 [DEBUG] Line 4\n"
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreaterEqual(len(stacktraces[0].context_before), 4)

    def test_context_lines_zero(self):
        """Test with context_lines=0."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file, include_context_lines=0)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(len(stacktraces[0].context_before), 0)

    def test_context_lines_limited_by_available(self):
        """Test that context lines don't exceed available lines."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file, include_context_lines=10)
        self.assertGreater(len(stacktraces), 0)
        self.assertLessEqual(len(stacktraces[0].context_before), 1)

    # ==================== Stacktrace Metadata Extraction Tests ====================

    def test_timestamp_extraction(self):
        """Test timestamp extraction from stacktrace header."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertIsNotNone(stacktraces[0].timestamp)

    def test_log_level_extraction(self):
        """Test log level extraction."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].log_level, 'ERROR')

    def test_service_extraction(self):
        """Test service name extraction."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].service_name, 'DBService')

    def test_error_code_extraction(self):
        """Test error code extraction."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - CRJAZ1282E Database error\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].error_code, 'CRJAZ1282E')

    def test_exception_type_extraction_from_header(self):
        """Test exception type extraction from header line."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] NullPointerException thrown\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].exception_type, 'NullPointerException')

    def test_exception_type_extraction_from_stacktrace(self):
        """Test exception type extraction from stacktrace body."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00 Caused by: IOException\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)

    # ==================== Min Stack Depth Tests ====================

    def test_min_stack_depth_filtering(self):
        """Test that min_stack_depth filters small stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file, min_stack_depth=2)
        self.assertGreater(len(stacktraces), 0)
        for st in stacktraces:
            self.assertGreaterEqual(len(st.lines) - 1, 2)

    def test_min_stack_depth_zero(self):
        """Test with min_stack_depth=0."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file, min_stack_depth=0)
        self.assertGreater(len(stacktraces), 0)

    # ==================== Deduplication Tests ====================

    def test_deduplication(self):
        """Test stacktrace deduplication."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces_with_dedup, summary1 = extract_stacktraces(temp_file, deduplicate=True)
        stacktraces_without_dedup, summary2 = extract_stacktraces(temp_file, deduplicate=False)
        
        self.assertLessEqual(len(stacktraces_with_dedup), len(stacktraces_without_dedup))

    # ==================== Stacktrace Line Detection Tests ====================

    def test_stacktrace_line_with_at_pattern(self):
        """Test detection of stacktrace lines with 'at' pattern."""
        self.assertTrue(_is_stacktrace_line("     at com.example.Class.method(Class.java:10)"))
        self.assertTrue(_is_stacktrace_line("2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)"))

    def test_stacktrace_line_with_caused_by(self):
        """Test detection of 'Caused by' lines."""
        self.assertTrue(_is_stacktrace_line("Caused by: java.lang.NullPointerException"))
        self.assertTrue(_is_stacktrace_line("    Caused by: IOException"))

    def test_stacktrace_line_with_ellipsis(self):
        """Test detection of '... N more' lines."""
        self.assertTrue(_is_stacktrace_line("    ... 5 more"))

    def test_non_stacktrace_line(self):
        """Test that normal log lines are not detected as stacktrace."""
        self.assertFalse(_is_stacktrace_line("2024-01-01 10:00:00 [INFO] Normal log message"))
        self.assertFalse(_is_stacktrace_line("[ERROR] Error message without stacktrace"))

    # ==================== Header Detection Tests ====================

    def test_stacktrace_header_detection(self):
        """Test stacktrace header detection."""
        header = "2024-01-01 10:00:00 [ERROR] Error occurred"
        next_line = "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)"
        
        self.assertTrue(_is_stacktrace_header(header, next_line))

    def test_stacktrace_header_with_exception(self):
        """Test header detection when exception is in header."""
        header = "2024-01-01 10:00:00 [ERROR] NullPointerException thrown"
        next_line = "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)"
        
        self.assertTrue(_is_stacktrace_header(header, next_line))

    def test_non_stacktrace_header(self):
        """Test that non-error headers are not detected."""
        header = "2024-01-01 10:00:00 [INFO] Info message"
        next_line = "2024-01-01 10:01:00 [DEBUG] Debug message"
        
        self.assertFalse(_is_stacktrace_header(header, next_line))

    # ==================== Summary Tests ====================

    def test_summary_total_count(self):
        """Test summary total stacktraces count."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(summary.total_stacktraces, len(stacktraces))

    def test_summary_exception_counts(self):
        """Test summary exception type counts."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] NullPointerException thrown\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] IOException occurred\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
            "2024-01-01 10:02:00 [ERROR] NullPointerException thrown\n"
            "2024-01-01 10:02:00     at com.example.Class3.method3(Class3.java:30)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertIn('NullPointerException', summary.counts_by_exception)
        self.assertGreater(summary.counts_by_exception.get('NullPointerException', 0), 0)

    def test_summary_service_counts(self):
        """Test summary service counts."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] PaymentService - Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertIn('DBService', summary.counts_by_service)
        self.assertIn('PaymentService', summary.counts_by_service)

    def test_summary_top_frequent_traces(self):
        """Test summary top frequent traces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(summary.top_frequent_traces), 0)

    # ==================== File Output Tests ====================

    def test_extract_to_files_creates_clean_log(self):
        """Test that extract_stacktraces_to_files creates clean log file."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info message\n"
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:01:00 [INFO] Another info\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        self.assertIn('clean_log', result_files)
        self.assertTrue(os.path.exists(result_files['clean_log']))
        
        with open(result_files['clean_log'], 'r') as f:
            clean_content = f.read()
            self.assertNotIn('at com.example.Class.method', clean_content)

    def test_extract_to_files_creates_stacktrace_file(self):
        """Test that extract_stacktraces_to_files creates stacktrace file."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        self.assertIn('stacktraces', result_files)
        self.assertTrue(os.path.exists(result_files['stacktraces']))
        
        with open(result_files['stacktraces'], 'r') as f:
            stacktrace_content = f.read()
            self.assertIn('at com.example.Class.method', stacktrace_content)

    def test_extract_to_files_creates_summary_file(self):
        """Test that extract_stacktraces_to_files creates summary file."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        self.assertIn('summary', result_files)
        self.assertTrue(os.path.exists(result_files['summary']))
        
        with open(result_files['summary'], 'r') as f:
            summary_content = f.read()
            self.assertIn('STACKTRACE EXTRACTION SUMMARY', summary_content)

    def test_extract_to_files_output_directory(self):
        """Test that output files are created in output directory."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        for file_path in result_files.values():
            self.assertIn('output', file_path)
            self.assertTrue(os.path.exists(file_path))

    def test_extract_to_files_filename_format(self):
        """Test that output files have correct naming format."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        temp_basename = os.path.basename(temp_file)
        temp_name_without_ext = os.path.splitext(temp_basename)[0]
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        self.assertIn(f'{temp_name_without_ext}_clean.log', result_files['clean_log'])
        self.assertIn(f'{temp_name_without_ext}_stack_trace.log', result_files['stacktraces'])
        self.assertIn(f'{temp_name_without_ext}_stacktrace_summary.txt', result_files['summary'])

    # ==================== Format Summary Tests ====================

    def test_format_summary_basic(self):
        """Test format_stacktrace_summary produces output."""
        summary = StacktraceSummary(
            total_stacktraces=5,
            counts_by_exception={'NullPointerException': 3, 'IOException': 2},
            counts_by_service={'DBService': 2, 'PaymentService': 3},
            top_frequent_traces=[('signature1', 2), ('signature2', 1)]
        )
        
        formatted = format_stacktrace_summary(summary)
        
        self.assertIsInstance(formatted, str)
        self.assertGreater(len(formatted), 0)
        self.assertIn('STACKTRACE EXTRACTION SUMMARY', formatted)
        self.assertIn('Total Stacktraces Found: 5', formatted)

    def test_format_summary_with_exceptions(self):
        """Test format_stacktrace_summary includes exception counts."""
        summary = StacktraceSummary(
            total_stacktraces=3,
            counts_by_exception={'NullPointerException': 2, 'IOException': 1},
            counts_by_service={},
            top_frequent_traces=[]
        )
        
        formatted = format_stacktrace_summary(summary)
        self.assertIn('NullPointerException', formatted)
        self.assertIn('IOException', formatted)

    def test_format_summary_with_services(self):
        """Test format_stacktrace_summary includes service counts."""
        summary = StacktraceSummary(
            total_stacktraces=3,
            counts_by_exception={},
            counts_by_service={'DBService': 2, 'PaymentService': 1},
            top_frequent_traces=[]
        )
        
        formatted = format_stacktrace_summary(summary)
        self.assertIn('DBService', formatted)
        self.assertIn('PaymentService', formatted)

    # ==================== Edge Cases ====================

    def test_stacktrace_with_multiple_at_lines(self):
        """Test stacktrace with multiple 'at' lines."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Class2.method2(Class2.java:20)\n"
            "2024-01-01 10:00:00     at com.example.Class3.method3(Class3.java:30)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreater(len(stacktraces[0].lines), 3)

    def test_stacktrace_with_caused_by(self):
        """Test stacktrace with 'Caused by' chain."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00 Caused by: IOException\n"
            "2024-01-01 10:00:00     at com.example.Reader.read(Reader.java:5)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreater(len(stacktraces[0].lines), 2)

    def test_consecutive_stacktraces(self):
        """Test handling of consecutive stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 2)

    def test_stacktrace_with_empty_lines(self):
        """Test handling of empty lines in stacktrace."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "\n"
            "2024-01-01 10:01:00 [INFO] Next message\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)

    def test_stacktrace_stops_at_normal_log_line(self):
        """Test that stacktrace collection stops at normal log line."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:01:00 [INFO] Normal log line\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(len(stacktraces[0].lines), 2)

    def test_signature_normalization(self):
        """Test signature normalization."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertIn('com.example.Class.method', stacktraces[0].signature)

    def test_line_number_tracking(self):
        """Test that start_line and end_line are tracked correctly."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Line 1\n"
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreater(stacktraces[0].end_line, stacktraces[0].start_line)

    def test_clean_log_removes_all_stacktrace_lines(self):
        """Test that clean log removes all stacktrace-related lines."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info 1\n"
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
            "2024-01-01 10:01:00 [INFO] Info 2\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        with open(result_files['clean_log'], 'r') as f:
            clean_lines = f.readlines()
            clean_content = '\n'.join(clean_lines)
            
            self.assertNotIn('at com.example.Class.method', clean_content)
            self.assertNotIn('at com.example.Other.run', clean_content)
            self.assertIn('Info 1', clean_content)
            self.assertIn('Info 2', clean_content)

    def test_stacktrace_file_contains_all_stacktraces(self):
        """Test that stacktrace file contains all extracted stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:01:00     at com.example.Class2.method2(Class2.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        result_files = extract_stacktraces_to_files(temp_file)
        
        with open(result_files['stacktraces'], 'r') as f:
            stacktrace_content = f.read()
            self.assertIn('Error 1', stacktrace_content)
            self.assertIn('Error 2', stacktrace_content)
            self.assertIn('at com.example.Class1.method1', stacktrace_content)
            self.assertIn('at com.example.Class2.method2', stacktrace_content)

    def test_original_file_unchanged(self):
        """Test that original file is not modified."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        original_content = open(temp_file, 'r').read()
        
        extract_stacktraces_to_files(temp_file)
        
        after_content = open(temp_file, 'r').read()
        self.assertEqual(original_content, after_content)

    # ==================== Real-world Format Tests ====================

    def test_real_world_log_format(self):
        """Test with real-world log format."""
        log_content = (
            "2025-01-12 09:15:05 [ERROR] DBService - CRJAZ1282E Database connection failure\n"
            "2025-01-12 09:15:05     at com.db.Driver.connect(Driver.java:88)\n"
            "2025-01-12 09:15:05     at com.db.ConnectionPool.getConnection(ConnectionPool.java:130)\n"
            "2025-01-12 09:15:05     at com.app.OrderRepo.fetchOrder(OrderRepo.java:52)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(stacktraces[0].service_name, 'DBService')
        self.assertEqual(stacktraces[0].error_code, 'CRJAZ1282E')
        self.assertEqual(len(stacktraces[0].lines), 4)

    def test_stacktrace_with_timestamp_on_each_line(self):
        """Test stacktrace where each line has timestamp."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(len(stacktraces[0].lines), 3)

    # ==================== Helper Function Tests ====================

    def test_extract_timestamp_helper(self):
        """Test _extract_timestamp helper function."""
        line = "2024-01-01 10:00:00 [ERROR] Error message"
        timestamp = _extract_timestamp(line)
        self.assertIsNotNone(timestamp)
        self.assertIsInstance(timestamp, datetime)

    def test_extract_log_level_helper(self):
        """Test _extract_log_level helper function."""
        line = "2024-01-01 10:00:00 [ERROR] Error message"
        level = _extract_log_level(line)
        self.assertEqual(level, 'ERROR')

    def test_extract_service_helper(self):
        """Test _extract_service helper function."""
        line = "2024-01-01 10:00:00 [ERROR] DBService - Error message"
        service = _extract_service(line)
        self.assertEqual(service, 'DBService')

    def test_extract_error_code_helper(self):
        """Test _extract_error_code helper function."""
        line = "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Database error"
        code = _extract_error_code(line)
        self.assertEqual(code, 'CRJAZ1282E')

    def test_extract_exception_type_helper(self):
        """Test _extract_exception_type helper function."""
        line = "2024-01-01 10:00:00 [ERROR] NullPointerException thrown"
        exc_type = _extract_exception_type(line)
        self.assertEqual(exc_type, 'NullPointerException')

    def test_normalize_signature_helper(self):
        """Test _normalize_signature helper function."""
        lines = [
            "2024-01-01 10:00:00 [ERROR] Error occurred",
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)",
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)"
        ]
        signature = _normalize_signature(lines)
        self.assertIn('com.example.Class.method', signature)
        self.assertIn('com.example.Other.run', signature)

    # ==================== Special Cases ====================

    def test_error_without_stacktrace(self):
        """Test ERROR line without following stacktrace."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message without stacktrace"
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 0)

    def test_error_followed_by_non_stacktrace_line(self):
        """Test ERROR line followed by non-stacktrace line."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:01:00 [INFO] Normal log line\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertEqual(len(stacktraces), 0)

    def test_multiline_stacktrace(self):
        """Test stacktrace spanning multiple lines."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class1.method1(Class1.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Class2.method2(Class2.java:20)\n"
            "2024-01-01 10:00:00     at com.example.Class3.method3(Class3.java:30)\n"
            "2024-01-01 10:00:00     at com.example.Class4.method4(Class4.java:40)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreater(len(stacktraces[0].lines), 4)

    def test_stacktrace_with_whitespace_variations(self):
        """Test stacktrace with different whitespace patterns."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error occurred\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00\tat com.example.Other.run(Other.java:20)\n"
            "2024-01-01 10:00:00  at com.example.Third.call(Third.java:30)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertGreater(len(stacktraces[0].lines), 3)

    def test_large_file_handling(self):
        """Test handling of large log file."""
        lines = []
        for i in range(100):
            if i % 10 == 0:
                lines.append(f"2024-01-01 10:00:{i:02d} [ERROR] Error {i}\n")
                lines.append(f"2024-01-01 10:00:{i:02d}     at com.example.Class{i}.method(Class{i}.java:{i})\n")
            else:
                lines.append(f"2024-01-01 10:00:{i:02d} [INFO] Info {i}\n")
        
        log_content = ''.join(lines)
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)
        self.assertEqual(summary.total_stacktraces, len(stacktraces))

    def test_unicode_in_stacktrace(self):
        """Test handling of unicode characters in stacktrace."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error: 错误 エラー\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        stacktraces, summary = extract_stacktraces(temp_file)
        self.assertGreater(len(stacktraces), 0)


if __name__ == '__main__':
    unittest.main()

