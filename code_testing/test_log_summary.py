import unittest
import os
import tempfile
from datetime import datetime
from utilities.log_summary import (
    summarize_log,
    format_summary,
    summarize_log_to_file,
    LogSummary,
    ErrorCodeInfo,
    StacktraceInfo,
    run_log_summary
)


class TestLogSummary(unittest.TestCase):
    """Unit tests for the log_summary module."""

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
        """Test that summarize_log handles non-existent file gracefully."""
        result = summarize_log('nonexistent_file.log')
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 0)

    def test_file_path_invalid(self):
        """Test handling of invalid file path."""
        result = summarize_log('/invalid/path/to/file.log')
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 0)

    def test_file_exists_and_readable(self):
        """Test that existing file is read correctly."""
        log_content = "2024-01-01 10:00:00 [ERROR] Test error message\n2024-01-01 10:01:00 [INFO] Test info message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = summarize_log(temp_file)
        self.assertIsInstance(result, LogSummary)
        self.assertGreater(result.total_lines, 0)

    # ==================== File Opening Tests ====================

    def test_file_encoding_utf8(self):
        """Test file opening with UTF-8 encoding."""
        log_content = "2024-01-01 10:00:00 [ERROR] Test with unicode: émoji 🎉\n2024-01-01 10:01:00 [INFO] Normal message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = summarize_log(temp_file)
        self.assertIsInstance(result, LogSummary)
        self.assertGreater(result.total_lines, 0)

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
        temp_file.write(b"2024-01-01 10:01:00 [INFO] Another line\n")
        temp_file.close()
        self.temp_files.append(temp_file.name)
        
        result = summarize_log(temp_file.name)
        self.assertIsInstance(result, LogSummary)

    def test_empty_file(self):
        """Test handling of empty log file."""
        temp_file = self._create_temp_log_file("")
        
        result = summarize_log(temp_file)
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 0)
        self.assertIsNone(result.first_timestamp)
        self.assertIsNone(result.last_timestamp)

    def test_file_with_only_whitespace(self):
        """Test handling of file with only whitespace."""
        temp_file = self._create_temp_log_file("   \n\t\n  \n")
        
        result = summarize_log(temp_file)
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 0)

    # ==================== Input Type Tests ====================

    def test_string_input(self):
        """Test summarize_log with string input."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        result = summarize_log(log_content)
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 2)

    def test_list_input(self):
        """Test summarize_log with list of strings input."""
        log_content = [
            "2024-01-01 10:00:00 [ERROR] Error message",
            "2024-01-01 10:01:00 [INFO] Info message",
            "2024-01-01 10:02:00 [ERROR] Another error"
        ]
        result = summarize_log(log_content)
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 3)

    def test_file_path_input(self):
        """Test summarize_log with file path input."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = summarize_log(temp_file)
        self.assertIsInstance(result, LogSummary)
        self.assertEqual(result.total_lines, 2)

    # ==================== Timestamp Extraction Tests ====================

    def test_timestamp_extraction_iso_format(self):
        """Test timestamp extraction with ISO format."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-15 14:30:00 [INFO] Info message"
        result = summarize_log(log_content)
        
        self.assertIsNotNone(result.first_timestamp)
        self.assertIsNotNone(result.last_timestamp)
        self.assertLess(result.first_timestamp, result.last_timestamp)

    def test_timestamp_extraction_iso_t_format(self):
        """Test timestamp extraction with ISO T format."""
        log_content = "2024-01-01T10:00:00 [ERROR] Error message\n2024-01-15T14:30:00 [INFO] Info message"
        result = summarize_log(log_content)
        
        self.assertIsNotNone(result.first_timestamp)
        self.assertIsNotNone(result.last_timestamp)

    def test_no_timestamps_in_log(self):
        """Test handling of log with no timestamps."""
        log_content = "[ERROR] Error message\n[INFO] Info message"
        result = summarize_log(log_content)
        
        self.assertIsNone(result.first_timestamp)
        self.assertIsNone(result.last_timestamp)
        self.assertEqual(result.time_range_hours, 0.0)

    def test_timestamp_range_calculation(self):
        """Test time range calculation."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] First message\n"
            "2024-01-01 12:00:00 [INFO] Second message\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.time_range_hours, 0)
        self.assertAlmostEqual(result.time_range_hours, 2.0, places=1)

    # ==================== Log Level Tests ====================

    def test_log_level_extraction_all_levels(self):
        """Test extraction of all standard log levels."""
        log_content = (
            "2024-01-01 10:00:00 [TRACE] Trace message\n"
            "2024-01-01 10:01:00 [DEBUG] Debug message\n"
            "2024-01-01 10:02:00 [INFO] Info message\n"
            "2024-01-01 10:03:00 [WARN] Warn message\n"
            "2024-01-01 10:04:00 [ERROR] Error message\n"
            "2024-01-01 10:05:00 [FATAL] Fatal message\n"
            "2024-01-01 10:06:00 [CRITICAL] Critical message\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.log_level_counts.get('TRACE', 0), 0)
        self.assertGreater(result.log_level_counts.get('DEBUG', 0), 0)
        self.assertGreater(result.log_level_counts.get('INFO', 0), 0)
        self.assertGreater(result.log_level_counts.get('WARN', 0), 0)
        self.assertGreater(result.log_level_counts.get('ERROR', 0), 0)
        self.assertGreater(result.log_level_counts.get('FATAL', 0), 0)
        self.assertGreater(result.log_level_counts.get('CRITICAL', 0), 0)

    def test_log_level_bracket_format(self):
        """Test log level extraction with bracket format: [ERROR]."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        result = summarize_log(log_content)
        
        self.assertEqual(result.log_level_counts.get('ERROR', 0), 1)
        self.assertEqual(result.log_level_counts.get('INFO', 0), 1)

    def test_log_level_colon_format(self):
        """Test log level extraction with colon format: ERROR:."""
        log_content = "2024-01-01 10:00:00 ERROR: Error message\n2024-01-01 10:01:00 INFO: Info message"
        result = summarize_log(log_content)
        
        self.assertEqual(result.log_level_counts.get('ERROR', 0), 1)
        self.assertEqual(result.log_level_counts.get('INFO', 0), 1)

    def test_log_level_space_format(self):
        """Test log level extraction with space format: ERROR ."""
        log_content = "2024-01-01 10:00:00 ERROR Error message\n2024-01-01 10:01:00 INFO Info message"
        result = summarize_log(log_content)
        
        self.assertGreater(result.log_level_counts.get('ERROR', 0), 0)

    def test_no_log_levels_in_log(self):
        """Test handling of log with no log levels."""
        log_content = "2024-01-01 10:00:00 Some message without level\n2024-01-01 10:01:00 Another message"
        result = summarize_log(log_content)
        
        self.assertEqual(sum(result.log_level_counts.values()), 0)

    def test_error_ratio_calculation(self):
        """Test error ratio calculation."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:01:00 [ERROR] Error 2\n"
            "2024-01-01 10:02:00 [INFO] Info 1\n"
            "2024-01-01 10:03:00 [INFO] Info 2\n"
            "2024-01-01 10:04:00 [INFO] Info 3\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.error_ratio, 0)
        self.assertLess(result.error_ratio, 100)

    def test_health_status_calculation(self):
        """Test health status calculation."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:01:00 [INFO] Info 1\n"
            "2024-01-01 10:02:00 [INFO] Info 2\n"
            "2024-01-01 10:03:00 [INFO] Info 3\n"
        )
        result = summarize_log(log_content)
        
        self.assertIn(result.health_status, ['HEALTHY', 'WARNING', 'CRITICAL', 'UNKNOWN'])

    # ==================== Error Code Tests ====================

    def test_error_code_extraction(self):
        """Test error code extraction."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - CRJAZ1282E Database connection failure\n"
            "2024-01-01 10:01:00 [ERROR] PaymentService - PAY4001E Payment failure\n"
            "2024-01-01 10:02:00 [ERROR] DBService - CRJAZ1282E Another error\n"
        )
        result = summarize_log(log_content)
        
        self.assertIn('CRJAZ1282E', result.error_codes)
        self.assertIn('PAY4001E', result.error_codes)
        self.assertEqual(result.error_codes['CRJAZ1282E'].count, 2)
        self.assertEqual(result.error_codes['PAY4001E'].count, 1)

    def test_error_code_patterns(self):
        """Test various error code patterns."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Error\n"
            "2024-01-01 10:01:00 [ERROR] NET6001E Error\n"
            "2024-01-01 10:02:00 [ERROR] PAY4001E Error\n"
            "2024-01-01 10:03:00 [ERROR] DEPLOY501E Error\n"
            "2024-01-01 10:04:00 [ERROR] FILE404E Error\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.error_codes), 0)

    def test_error_code_categorization(self):
        """Test error code categorization."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Database error\n"
            "2024-01-01 10:01:00 [ERROR] NET6001E Network error\n"
        )
        result = summarize_log(log_content)
        
        self.assertIn('CRJAZ1282E', result.error_codes)
        self.assertIn('NET6001E', result.error_codes)

    def test_error_code_first_last_timestamps(self):
        """Test error code first and last timestamps."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E First occurrence\n"
            "2024-01-01 10:01:00 [INFO] Some info\n"
            "2024-01-01 10:02:00 [ERROR] CRJAZ1282E Second occurrence\n"
        )
        result = summarize_log(log_content)
        
        error_info = result.error_codes.get('CRJAZ1282E')
        if error_info:
            self.assertIsNotNone(error_info.first_timestamp)
            self.assertIsNotNone(error_info.last_timestamp)
            self.assertEqual(error_info.count, 2)

    def test_dominant_error_code(self):
        """Test dominant error code detection."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Error 1\n"
            "2024-01-01 10:01:00 [ERROR] CRJAZ1282E Error 2\n"
            "2024-01-01 10:02:00 [ERROR] CRJAZ1282E Error 3\n"
            "2024-01-01 10:03:00 [ERROR] CRJAZ1282E Error 4\n"
            "2024-01-01 10:04:00 [ERROR] PAY4001E Error 5\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(result.dominant_error_code, 'CRJAZ1282E')

    def test_no_error_codes_in_log(self):
        """Test handling of log with no error codes."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info message\n"
            "2024-01-01 10:01:00 [DEBUG] Debug message\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(len(result.error_codes), 0)
        self.assertIsNone(result.dominant_error_code)

    # ==================== Stacktrace Tests ====================

    def test_stacktrace_detection(self):
        """Test stacktrace detection."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] NullPointerException thrown\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.stacktraces), 0)

    def test_stacktrace_exception_extraction(self):
        """Test exception type extraction from stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - NullPointerException thrown\n"
            "2024-01-01 10:00:00     at com.example.db.ConnectionPool.get(ConnectionPool.java:110)\n"
            "2024-01-01 10:00:01 [ERROR] FileService - IOException occurred\n"
            "2024-01-01 10:00:01     at com.file.Reader.open(Reader.java:31)\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.stacktraces), 0)

    def test_stacktrace_line_count(self):
        """Test stacktrace line count."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
            "2024-01-01 10:00:00     at com.example.Other.run(Other.java:20)\n"
            "2024-01-01 10:00:00     at com.example.Third.process(Third.java:30)\n"
        )
        result = summarize_log(log_content)
        
        if result.stacktraces:
            self.assertGreaterEqual(result.stacktraces[0].line_count, 1)

    def test_large_stacktrace_detection(self):
        """Test detection of large stacktraces (>10 lines)."""
        stacktrace_lines = [
            "2024-01-01 10:00:00 [ERROR] Error message\n"
        ]
        for i in range(15):
            stacktrace_lines.append(f"2024-01-01 10:00:00     at com.example.Class{i}.method(Class{i}.java:{i})\n")
        
        log_content = ''.join(stacktrace_lines)
        result = summarize_log(log_content)
        
        if result.stacktraces:
            large_stacktraces = [st for st in result.stacktraces if st.line_count > 10]
            self.assertGreater(len(large_stacktraces), 0)

    def test_no_stacktraces_in_log(self):
        """Test handling of log with no stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:01:00 [INFO] Info message\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(len(result.stacktraces), 0)

    # ==================== Service Extraction Tests ====================

    def test_service_extraction(self):
        """Test service extraction from log lines."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] DBService - Error message\n"
            "2024-01-01 10:01:00 [INFO] PaymentService - Info message\n"
            "2024-01-01 10:02:00 [WARN] AuthService - Warning message\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.services_involved), 0)
        self.assertIn('DBService', result.services_involved)
        self.assertIn('PaymentService', result.services_involved)

    def test_no_services_in_log(self):
        """Test handling of log with no services."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:01:00 [INFO] Info message\n"
        )
        result = summarize_log(log_content)
        
        self.assertIsInstance(result.services_involved, list)

    # ==================== Time-based Analysis Tests ====================

    def test_peak_error_minute(self):
        """Test peak error minute detection."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:00:05 [ERROR] Error 2\n"
            "2024-01-01 10:00:10 [ERROR] Error 3\n"
            "2024-01-01 10:01:00 [ERROR] Error 4\n"
        )
        result = summarize_log(log_content)
        
        if result.peak_error_minute:
            self.assertIsInstance(result.peak_error_minute, datetime)
            self.assertGreater(result.peak_error_count, 0)

    def test_high_error_windows(self):
        """Test high error activity windows detection."""
        log_content = []
        for i in range(10):
            log_content.append(f"2024-01-01 10:00:{i:02d} [ERROR] Error {i}\n")
        for i in range(10, 20):
            log_content.append(f"2024-01-01 10:01:{i:02d} [INFO] Info {i}\n")
        
        result = summarize_log(''.join(log_content))
        
        self.assertIsInstance(result.high_error_windows, list)

    # ==================== Root Cause Hints Tests ====================

    def test_root_cause_hints_generation(self):
        """Test root cause hints generation."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Database error\n"
            "2024-01-01 10:01:00 [ERROR] CRJAZ1282E Database error\n"
            "2024-01-01 10:02:00 [ERROR] CRJAZ1282E Database error\n"
        )
        result = summarize_log(log_content)
        
        self.assertIsInstance(result.root_cause_hints, list)

    # ==================== Format Summary Tests ====================

    def test_format_summary_basic(self):
        """Test format_summary produces output."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:01:00 [INFO] Info message\n"
        )
        summary = summarize_log(log_content)
        formatted = format_summary(summary)
        
        self.assertIsInstance(formatted, str)
        self.assertGreater(len(formatted), 0)
        self.assertIn('LOG SUMMARY REPORT', formatted)

    def test_format_summary_with_error_codes(self):
        """Test format_summary with error codes."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Database error\n"
            "2024-01-01 10:01:00 [ERROR] NET6001E Network error\n"
        )
        summary = summarize_log(log_content)
        formatted = format_summary(summary)
        
        self.assertIn('ERROR CODE ANALYSIS', formatted)
        self.assertIn('CRJAZ1282E', formatted)

    def test_format_summary_with_stacktraces(self):
        """Test format_summary with stacktraces."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        summary = summarize_log(log_content)
        formatted = format_summary(summary)
        
        self.assertIn('STACKTRACE ANALYSIS', formatted)

    def test_format_summary_empty(self):
        """Test format_summary with empty summary."""
        summary = LogSummary()
        formatted = format_summary(summary)
        
        self.assertIsInstance(formatted, str)
        self.assertGreater(len(formatted), 0)

    def test_format_summary_colors(self):
        """Test format_summary with and without colors."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n"
        summary = summarize_log(log_content)
        
        formatted_with_colors = format_summary(summary, use_colors=True)
        formatted_without_colors = format_summary(summary, use_colors=False)
        
        self.assertIsInstance(formatted_with_colors, str)
        self.assertIsInstance(formatted_without_colors, str)

    # ==================== Summarize Log To File Tests ====================

    def test_summarize_log_to_file_with_output_path(self):
        """Test summarize_log_to_file with specified output path."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error 1\n"
            "2024-01-01 10:01:00 [INFO] Info 1\n"
        )
        temp_file = self._create_temp_log_file(log_content)
        
        output_file = os.path.join(self.temp_dir, 'summary_output.txt')
        result_file = summarize_log_to_file(temp_file, output_file)
        
        self.assertEqual(result_file, output_file)
        self.assertTrue(os.path.exists(output_file))
        
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('LOG SUMMARY REPORT', content)

    def test_summarize_log_to_file_temp_file(self):
        """Test summarize_log_to_file without output path (creates temp file)."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error 1\n"
        temp_file = self._create_temp_log_file(log_content)
        
        result_file = summarize_log_to_file(temp_file)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))
        self.assertTrue(result_file.endswith('.txt'))
        
        with open(result_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn('LOG SUMMARY REPORT', content)

    def test_summarize_log_to_file_string_input(self):
        """Test summarize_log_to_file with string input."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n"
        output_file = os.path.join(self.temp_dir, 'string_summary.txt')
        result_file = summarize_log_to_file(log_content, output_file)
        self.temp_files.append(result_file)
        
        self.assertTrue(os.path.exists(result_file))

    # ==================== Edge Cases ====================

    def test_empty_lines(self):
        """Test handling of empty lines in log file."""
        log_content = "\n\n2024-01-01 10:00:00 [ERROR] Error message\n\n2024-01-01 10:01:00 [INFO] Info message\n\n"
        result = summarize_log(log_content)
        
        self.assertEqual(result.total_lines, 2)

    def test_whitespace_only_lines(self):
        """Test handling of whitespace-only lines."""
        log_content = "   \n\t\n2024-01-01 10:00:00 [ERROR] Error message\n  \n2024-01-01 10:01:00 [INFO] Info message"
        result = summarize_log(log_content)
        
        self.assertEqual(result.total_lines, 2)

    def test_lines_without_log_level(self):
        """Test handling of lines without log levels."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "This is a line without a log level\n"
            "2024-01-01 10:01:00 [INFO] Info message\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreaterEqual(result.total_lines, 2)

    def test_single_line_log(self):
        """Test handling of single line log."""
        log_content = "2024-01-01 10:00:00 [ERROR] Single error message"
        result = summarize_log(log_content)
        
        self.assertEqual(result.total_lines, 1)
        self.assertIsNotNone(result.first_timestamp)
        self.assertIsNotNone(result.last_timestamp)

    def test_large_file_handling(self):
        """Test handling of large log file."""
        lines = []
        for i in range(100):
            if i % 10 == 0:
                lines.append(f"2024-01-01 10:00:{i:02d} [ERROR] Error message {i}\n")
            else:
                lines.append(f"2024-01-01 10:00:{i:02d} [INFO] Info message {i}\n")
        
        log_content = ''.join(lines)
        temp_file = self._create_temp_log_file(log_content)
        
        result = summarize_log(temp_file)
        self.assertEqual(result.total_lines, 100)

    def test_special_characters_in_messages(self):
        """Test handling of special characters in log messages."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error with special chars: !@#$%^&*()\n"
            "2024-01-01 10:01:00 [ERROR] Error with quotes: \"test\" 'test'\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(result.total_lines, 2)

    def test_unicode_in_log_messages(self):
        """Test handling of unicode characters in log messages."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Erreur: 错误 エラー خطأ\n"
            "2024-01-01 10:01:00 [ERROR] Error with emoji: 🚨 🔥 ⚠️\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(result.total_lines, 2)

    def test_mixed_format_log_file(self):
        """Test handling with mixed log formats in same file."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error with brackets\n"
            "2024-01-01 10:01:00 ERROR: Error with colon\n"
            "2024-01-01 10:02:00 ERROR  Error with spaces\n"
            "2024-01-01 10:03:00 [INFO] Info message\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreaterEqual(result.total_lines, 4)

    def test_multiple_error_codes_same_line(self):
        """Test handling of multiple error codes in same line."""
        log_content = "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Error and NET6001E Network issue"
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.error_codes), 0)

    def test_warn_vs_warning(self):
        """Test handling of WARN vs WARNING."""
        log_content = (
            "2024-01-01 10:00:00 [WARN] Warning message\n"
            "2024-01-01 10:01:00 [WARNING] Warning message full\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.log_level_counts.get('WARN', 0) + result.log_level_counts.get('WARNING', 0), 0)

    def test_err_vs_error(self):
        """Test handling of ERR vs ERROR."""
        log_content = (
            "2024-01-01 10:00:00 [ERR] Error short\n"
            "2024-01-01 10:01:00 [ERROR] Error full\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.log_level_counts.get('ERROR', 0), 0)

    def test_case_insensitive_level_matching(self):
        """Test that log level matching is case-insensitive."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [error] lowercase error"
        result = summarize_log(log_content)
        
        self.assertGreater(result.log_level_counts.get('ERROR', 0), 0)

    def test_no_matching_error_codes(self):
        """Test when no error codes match pattern."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Generic error message\n"
            "2024-01-01 10:01:00 [INFO] Info message\n"
        )
        result = summarize_log(log_content)
        
        self.assertEqual(len(result.error_codes), 0)

    def test_error_codes_with_various_lengths(self):
        """Test error codes with various lengths."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] ERR123E Short code\n"
            "2024-01-01 10:01:00 [ERROR] ABC1234E Medium code\n"
            "2024-01-01 10:02:00 [ERROR] LONGCODE1234E Long code\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.error_codes), 0)

    def test_stacktrace_without_exception_name(self):
        """Test stacktrace without explicit exception name."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] Error message\n"
            "2024-01-01 10:00:00     at com.example.Class.method(Class.java:10)\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(len(result.stacktraces), 0)

    def test_service_extraction_edge_cases(self):
        """Test service extraction with various formats."""
        log_content = (
            "2024-01-01 10:00:00 [ERROR] ServiceName - Error\n"
            "2024-01-01 10:01:00 [INFO] [AnotherService] - Info\n"
        )
        result = summarize_log(log_content)
        
        self.assertIsInstance(result.services_involved, list)

    def test_time_range_with_single_timestamp(self):
        """Test time range with single timestamp."""
        log_content = "2024-01-01 10:00:00 [ERROR] Single error message"
        result = summarize_log(log_content)
        
        self.assertEqual(result.time_range_hours, 0.0)

    def test_peak_error_with_no_errors(self):
        """Test peak error detection with no errors."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info message\n"
            "2024-01-01 10:01:00 [DEBUG] Debug message\n"
        )
        result = summarize_log(log_content)
        
        self.assertIsNone(result.peak_error_minute)

    def test_dominant_error_code_edge_case(self):
        """Test dominant error code with single error code."""
        log_content = "2024-01-01 10:00:00 [ERROR] CRJAZ1282E Single error"
        result = summarize_log(log_content)
        
        if result.error_codes:
            self.assertIsNotNone(result.dominant_error_code)

    def test_root_cause_hints_empty(self):
        """Test root cause hints with no hints."""
        log_content = (
            "2024-01-01 10:00:00 [INFO] Info message\n"
            "2024-01-01 10:01:00 [DEBUG] Debug message\n"
        )
        result = summarize_log(log_content)
        
        self.assertIsInstance(result.root_cause_hints, list)

    # ==================== Real-world Format Tests ====================

    def test_real_world_log_format(self):
        """Test with real-world log format."""
        log_content = (
            "2025-01-12 09:15:05 [ERROR] DBService - CRJAZ1282E Database connection failure\n"
            "2025-01-12 09:15:05     at com.db.Driver.connect(Driver.java:88)\n"
            "2025-01-12 09:15:05     at com.db.ConnectionPool.getConnection(ConnectionPool.java:130)\n"
            "2025-01-12 09:15:08 [INFO] NotificationService - Email sent user=jay\n"
        )
        result = summarize_log(log_content)
        
        self.assertGreater(result.total_lines, 0)
        self.assertIn('CRJAZ1282E', result.error_codes)
        self.assertGreater(len(result.stacktraces), 0)
        self.assertIn('DBService', result.services_involved)


    # ========== run_log_summary() Function Tests ==========
    
    def test_run_log_summary_success(self):
        """Test run_log_summary() returns correct dictionary structure on success."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message\n2024-01-01 10:01:00 [INFO] Info message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_log_summary(temp_file, output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["data"]["json"]["summary"])
        self.assertIsNotNone(result["artifacts"])
        self.assertTrue(len(result["artifacts"]) > 0)
        self.assertTrue(os.path.exists(result["artifacts"][0]["path"]))
        self.assertGreater(len(result["data"]["text"]), 0)
        self.assertEqual(len(result["errors"]), 0)
    
    def test_run_log_summary_file_not_found(self):
        """Test run_log_summary() handles file not found error."""
        result = run_log_summary("nonexistent_file.log")
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("File not found", result["errors"][0])
        self.assertEqual(len(result["artifacts"]), 0)
    
    def test_run_log_summary_no_write_file(self):
        """Test run_log_summary() with write_file=False."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_log_summary(temp_file, write_file=False)
        
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["data"]["json"]["summary"])
        self.assertEqual(len(result["artifacts"]), 0)  # No file created
        self.assertGreater(len(result["data"]["text"]), 0)
    
    def test_run_log_summary_custom_output_dir(self):
        """Test run_log_summary() with custom output directory."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message"
        temp_file = self._create_temp_log_file(log_content)
        custom_output_dir = os.path.join(self.temp_dir, "custom_output")
        
        result = run_log_summary(temp_file, output_dir=custom_output_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertTrue(len(result["artifacts"]) > 0)
        self.assertTrue(result["artifacts"][0]["path"].startswith(custom_output_dir))
        self.assertTrue(os.path.exists(custom_output_dir))
    
    def test_run_log_summary_formatted_summary(self):
        """Test run_log_summary() includes formatted summary text."""
        log_content = "2024-01-01 10:00:00 [ERROR] Error message"
        temp_file = self._create_temp_log_file(log_content)
        
        result = run_log_summary(temp_file, output_dir=self.temp_dir)
        
        self.assertEqual(result["status"], "success")
        self.assertIn("LOG SUMMARY", result["data"]["text"])
        self.assertIn("Total Lines", result["data"]["text"])


if __name__ == '__main__':
    unittest.main()

