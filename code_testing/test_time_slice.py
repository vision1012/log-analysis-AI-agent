import unittest
import os
import tempfile
from datetime import datetime, timedelta
from utilities.time_slice import slice_by_time, slice_by_time_range, slice_by_time_to_file, _extract_timestamp


class TestTimeSlice(unittest.TestCase):
    """Unit tests for the time_slice functions."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.temp_files = []
        self.test_start_time = datetime(2024, 1, 1, 10, 0, 0)
        self.test_end_time = datetime(2024, 1, 1, 11, 0, 0)

    def tearDown(self):
        """Clean up temporary files after each test method."""
        for temp_file in self.temp_files:
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def _create_temp_log_file(self, content):
        """Helper to create a temporary log file."""
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.log')
        temp_file.write(content)
        temp_file.close()
        self.temp_files.append(temp_file.name)
        return temp_file.name

    # ========== ISO 8601 Format Tests ==========
    
    def test_iso8601_basic_format(self):
        """Test ISO 8601 format: 2024-01-01T10:00:00"""
        log_content = """2024-01-01T09:30:00 Early log entry
2024-01-01T10:15:00 Middle log entry
2024-01-01T10:45:00 Later log entry
2024-01-01T11:30:00 Late log entry"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)
        self.assertIn("2024-01-01T10:15:00 Middle log entry", result)
        self.assertIn("2024-01-01T10:45:00 Later log entry", result)
        self.assertNotIn("2024-01-01T09:30:00 Early log entry", result)
        self.assertNotIn("2024-01-01T11:30:00 Late log entry", result)

    def test_iso8601_with_space(self):
        """Test ISO 8601 format with space: 2024-01-01 10:00:00"""
        log_content = """2024-01-01 09:30:00 Early log
2024-01-01 10:15:00 Middle log
2024-01-01 10:45:00 Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)
        self.assertIn("2024-01-01 10:15:00 Middle log", result)
        self.assertIn("2024-01-01 10:45:00 Later log", result)

    def test_iso8601_with_microseconds(self):
        """Test ISO 8601 format with microseconds"""
        log_content = """2024-01-01T10:15:30.123456 Log with microseconds
2024-01-01T10:30:45.789012 Another log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_iso8601_with_timezone(self):
        """Test ISO 8601 format with timezone"""
        log_content = """2024-01-01T10:15:00Z UTC log
2024-01-01T10:30:00+05:30 Timezone log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertGreaterEqual(len(result), 1)  # At least one should match

    # ========== Unix Timestamp Tests ==========
    
    def test_unix_timestamp_seconds(self):
        """Test Unix timestamp in seconds (10 digits)"""
        # Convert test times to Unix timestamps
        start_ts = int(self.test_start_time.timestamp())
        end_ts = int(self.test_end_time.timestamp())
        before_ts = start_ts - 3600
        during_ts = start_ts + 900
        after_ts = end_ts + 3600
        
        log_content = f"""{before_ts} Early log entry
{during_ts} Middle log entry
{after_ts} Late log entry"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)
        self.assertIn(f"{during_ts} Middle log entry", result)

    def test_unix_timestamp_milliseconds(self):
        """Test Unix timestamp in milliseconds (13 digits)"""
        start_ts_ms = int(self.test_start_time.timestamp() * 1000)
        end_ts_ms = int(self.test_end_time.timestamp() * 1000)
        during_ts_ms = start_ts_ms + 900000
        
        log_content = f"""{during_ts_ms} Log with millisecond timestamp"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)

    # ========== Apache/Nginx Format Tests ==========
    
    def test_apache_nginx_format(self):
        """Test Apache/Nginx log format"""
        log_content = """[01/Jan/2024:09:30:00 +0000] Early request
[01/Jan/2024:10:15:00 +0000] Middle request
[01/Jan/2024:10:45:00 +0000] Later request
[01/Jan/2024:11:30:00 +0000] Late request"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)
        self.assertIn("[01/Jan/2024:10:15:00 +0000] Middle request", result)
        self.assertIn("[01/Jan/2024:10:45:00 +0000] Later request", result)

    # ========== Syslog Format Tests ==========
    
    def test_syslog_format(self):
        """Test syslog format"""
        current_year = datetime.now().year
        log_content = f"""Jan  1 09:30:00 Early syslog
Jan  1 10:15:00 Middle syslog
Jan  1 10:45:00 Later syslog
Jan  1 11:30:00 Late syslog"""
        
        start_time = datetime(current_year, 1, 1, 10, 0, 0)
        end_time = datetime(current_year, 1, 1, 11, 0, 0)
        
        result = slice_by_time(log_content, start_time, end_time)
        self.assertEqual(len(result), 2)

    # ========== RFC 2822 Format Tests ==========
    
    def test_rfc2822_format(self):
        """Test RFC 2822 format"""
        log_content = """Mon, 01 Jan 2024 09:30:00 +0000 Early log
Mon, 01 Jan 2024 10:15:00 +0000 Middle log
Mon, 01 Jan 2024 10:45:00 +0000 Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    # ========== Bracket Format Tests ==========
    
    def test_bracket_format(self):
        """Test bracket format: [2024-01-01 10:00:00]"""
        log_content = """[2024-01-01 09:30:00] Early log
[2024-01-01 10:15:00] Middle log
[2024-01-01 10:45:00] Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_bracket_format_with_milliseconds(self):
        """Test bracket format with milliseconds"""
        log_content = """[2024-01-01 10:15:00.123] Log with milliseconds"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)

    # ========== Date Format Tests ==========
    
    def test_us_date_format(self):
        """Test US date format: MM/DD/YYYY HH:MM:SS"""
        log_content = """01/01/2024 09:30:00 Early log
01/01/2024 10:15:00 Middle log
01/01/2024 10:45:00 Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_european_date_format(self):
        """Test European date format: DD-MM-YYYY HH:MM:SS"""
        log_content = """01-01-2024 09:30:00 Early log
01-01-2024 10:15:00 Middle log
01-01-2024 10:45:00 Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_iso_date_format(self):
        """Test ISO date format: YYYY/MM/DD HH:MM:SS"""
        log_content = """2024/01/01 09:30:00 Early log
2024/01/01 10:15:00 Middle log
2024/01/01 10:45:00 Later log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    # ========== Time-Only Format Tests ==========
    
    def test_time_only_format(self):
        """Test time-only format: HH:MM:SS"""
        today = datetime.now().date()
        start_time = datetime.combine(today, datetime.now().time().replace(hour=10, minute=0, second=0))
        end_time = datetime.combine(today, datetime.now().time().replace(hour=11, minute=0, second=0))
        
        log_content = """09:30:00 Early log
10:15:00 Middle log
10:45:00 Later log
11:30:00 Late log"""
        
        result = slice_by_time(log_content, start_time, end_time)
        self.assertEqual(len(result), 2)

    def test_12_hour_format(self):
        """Test 12-hour format with AM/PM"""
        today = datetime.now().date()
        start_time = datetime.combine(today, datetime.now().time().replace(hour=10, minute=0, second=0))
        end_time = datetime.combine(today, datetime.now().time().replace(hour=11, minute=0, second=0))
        
        log_content = """09:30:00 AM Early log
10:15:00 AM Middle log
10:45:00 AM Later log
11:30:00 AM Late log"""
        
        result = slice_by_time(log_content, start_time, end_time)
        self.assertEqual(len(result), 2)

    # ========== Input Type Tests ==========
    
    def test_string_input(self):
        """Test with string input"""
        log_content = """2024-01-01T10:15:00 Log line 1
2024-01-01T10:30:00 Log line 2"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_list_input(self):
        """Test with list of strings input"""
        log_content = [
            "2024-01-01T09:30:00 Early log",
            "2024-01-01T10:15:00 Middle log",
            "2024-01-01T10:45:00 Later log"
        ]
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_file_path_input(self):
        """Test with file path input"""
        log_content = """2024-01-01T09:30:00 Early log
2024-01-01T10:15:00 Middle log
2024-01-01T10:45:00 Later log"""
        
        log_file = self._create_temp_log_file(log_content)
        result = slice_by_time(log_file, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_slice_by_time_range_function(self):
        """Test the convenience function slice_by_time_range"""
        log_content = """2024-01-01T10:15:00 Log line"""
        log_file = self._create_temp_log_file(log_content)
        
        result = slice_by_time_range(log_file, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)

    # ========== Edge Cases ==========
    
    def test_empty_log_content(self):
        """Test with empty log content"""
        result = slice_by_time("", self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 0)

    def test_empty_list_input(self):
        """Test with empty list input"""
        result = slice_by_time([], self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 0)

    def test_empty_file(self):
        """Test with empty file"""
        log_file = self._create_temp_log_file("")
        result = slice_by_time(log_file, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 0)

    def test_lines_without_timestamps(self):
        """Test logs with lines that don't have timestamps"""
        log_content = """This line has no timestamp
2024-01-01T10:15:00 This line has a timestamp
Another line without timestamp
2024-01-01T10:30:00 Another timestamp"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)
        self.assertNotIn("This line has no timestamp", result)
        self.assertNotIn("Another line without timestamp", result)

    def test_lines_with_empty_lines(self):
        """Test logs with empty lines"""
        log_content = """2024-01-01T10:15:00 First log

2024-01-01T10:30:00 Second log
"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)
        # Empty lines should be skipped

    def test_no_matching_logs(self):
        """Test when no logs match the time range"""
        log_content = """2024-01-01T08:00:00 Early log
2024-01-01T12:00:00 Late log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 0)

    def test_all_logs_match(self):
        """Test when all logs match the time range"""
        log_content = """2024-01-01T10:15:00 Log 1
2024-01-01T10:30:00 Log 2
2024-01-01T10:45:00 Log 3"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 3)

    def test_boundary_start_time(self):
        """Test boundary condition: logs exactly at start time"""
        log_content = """2024-01-01T10:00:00 Exact start time log
2024-01-01T10:15:00 After start log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)  # Both should be included (inclusive)

    def test_boundary_end_time(self):
        """Test boundary condition: logs exactly at end time"""
        log_content = """2024-01-01T10:45:00 Before end log
2024-01-01T11:00:00 Exact end time log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)  # Both should be included (inclusive)

    def test_boundary_before_start(self):
        """Test boundary condition: logs just before start time"""
        log_content = """2024-01-01T09:59:59 Just before start
2024-01-01T10:00:00 At start"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)
        self.assertIn("2024-01-01T10:00:00 At start", result)

    def test_boundary_after_end(self):
        """Test boundary condition: logs just after end time"""
        log_content = """2024-01-01T11:00:00 At end
2024-01-01T11:00:01 Just after end"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)
        self.assertIn("2024-01-01T11:00:00 At end", result)

    def test_invalid_time_range(self):
        """Test with invalid time range (start > end)"""
        log_content = """2024-01-01T10:15:00 Log entry"""
        start_time = datetime(2024, 1, 1, 11, 0, 0)
        end_time = datetime(2024, 1, 1, 10, 0, 0)
        
        result = slice_by_time(log_content, start_time, end_time)
        self.assertEqual(len(result), 0)  # No logs should match

    def test_same_start_end_time(self):
        """Test with same start and end time"""
        log_content = """2024-01-01T10:15:00 Log entry"""
        exact_time = datetime(2024, 1, 1, 10, 15, 0)
        
        result = slice_by_time(log_content, exact_time, exact_time)
        self.assertEqual(len(result), 1)  # Should include the exact match

    def test_invalid_timestamp_formats(self):
        """Test with invalid timestamp formats"""
        log_content = """Invalid timestamp format log
2024-13-45T25:99:99 Invalid date/time
2024-01-01T10:15:00 Valid log"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 1)
        self.assertIn("2024-01-01T10:15:00 Valid log", result)

    def test_mixed_timestamp_formats(self):
        """Test logs with mixed timestamp formats"""
        current_year = datetime.now().year
        log_content = f"""{current_year}-01-01T10:15:00 ISO format log
[01/Jan/{current_year}:10:20:00 +0000] Apache format log
Jan  1 10:25:00 Syslog format log"""
        
        # Use current year for start/end times to match all formats
        start_time = datetime(current_year, 1, 1, 10, 0, 0)
        end_time = datetime(current_year, 1, 1, 11, 0, 0)
        result = slice_by_time(log_content, start_time, end_time)
        # All three formats should be parsed and match the time range
        self.assertEqual(len(result), 3)
        # Check that all formats are parsed
        self.assertTrue(any("ISO format log" in line for line in result))
        self.assertTrue(any("Apache format log" in line for line in result))
        self.assertTrue(any("Syslog format log" in line for line in result))

    def test_large_log_file(self):
        """Test with a larger log file"""
        log_lines = []
        base_time = datetime(2024, 1, 1, 9, 0, 0)
        for i in range(100):
            timestamp = base_time + timedelta(minutes=i)
            log_lines.append(f"{timestamp.isoformat()} Log entry {i}")
        
        log_content = "\n".join(log_lines)
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        
        # Should have 60 entries (from 10:00 to 11:00, one per minute)
        self.assertGreater(len(result), 0)
        self.assertLessEqual(len(result), 61)  # Including boundaries

    def test_multiline_log_entries(self):
        """Test with multiline log entries"""
        log_content = """2024-01-01T10:15:00 First log line
    Continuation line 1
    Continuation line 2
2024-01-01T10:30:00 Second log entry"""
        
        result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        # Only lines with valid timestamps should be included
        self.assertGreaterEqual(len(result), 2)

    # ========== Timestamp Extraction Tests ==========
    
    def test_extract_timestamp_iso8601(self):
        """Test _extract_timestamp with ISO 8601 format"""
        line = "2024-01-01T10:15:30 Log message"
        timestamp = _extract_timestamp(line)
        self.assertIsNotNone(timestamp)
        self.assertEqual(timestamp.year, 2024)
        self.assertEqual(timestamp.month, 1)
        self.assertEqual(timestamp.day, 1)
        self.assertEqual(timestamp.hour, 10)
        self.assertEqual(timestamp.minute, 15)

    def test_extract_timestamp_unix(self):
        """Test _extract_timestamp with Unix timestamp"""
        test_time = datetime(2024, 1, 1, 10, 15, 30)
        unix_ts = int(test_time.timestamp())
        line = f"{unix_ts} Log message"
        timestamp = _extract_timestamp(line)
        self.assertIsNotNone(timestamp)
        # Allow for small differences due to timestamp precision
        self.assertAlmostEqual(timestamp.timestamp(), test_time.timestamp(), delta=1)

    def test_extract_timestamp_none(self):
        """Test _extract_timestamp returns None for invalid input"""
        line = "No timestamp in this line"
        timestamp = _extract_timestamp(line)
        self.assertIsNone(timestamp)

    def test_extract_timestamp_empty_string(self):
        """Test _extract_timestamp with empty string"""
        timestamp = _extract_timestamp("")
        self.assertIsNone(timestamp)

    def test_extract_timestamp_with_milliseconds_comma(self):
        """Test timestamp extraction with comma milliseconds"""
        line = "2024-01-01 10:15:30,123 Log with comma milliseconds"
        timestamp = _extract_timestamp(line)
        self.assertIsNotNone(timestamp)

    def test_extract_timestamp_with_milliseconds_dot(self):
        """Test timestamp extraction with dot milliseconds"""
        line = "2024-01-01 10:15:30.456 Log with dot milliseconds"
        timestamp = _extract_timestamp(line)
        self.assertIsNotNone(timestamp)

    # ========== File Handling Tests ==========
    
    def test_nonexistent_file(self):
        """Test with non-existent file path"""
        nonexistent_file = "/tmp/nonexistent_file_12345.log"
        # Should handle gracefully - treat as string content if not a file
        result = slice_by_time(nonexistent_file, self.test_start_time, self.test_end_time)
        # If it's not a file, it will be treated as string content and likely return empty
        self.assertIsInstance(result, list)

    def test_file_with_special_characters(self):
        """Test file with special characters in content"""
        log_content = """2024-01-01T10:15:00 Log with special chars: !@#$%^&*()
2024-01-01T10:30:00 Another log with "quotes" and 'apostrophes'"""
        log_file = self._create_temp_log_file(log_content)
        result = slice_by_time(log_file, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    def test_file_encoding_handling(self):
        """Test file encoding handling"""
        log_content = """2024-01-01T10:15:00 Log entry with UTF-8: ñoño
2024-01-01T10:30:00 Another entry"""
        log_file = self._create_temp_log_file(log_content)
        result = slice_by_time(log_file, self.test_start_time, self.test_end_time)
        self.assertEqual(len(result), 2)

    # ========== Time Range Edge Cases ==========
    
    def test_very_short_time_range(self):
        """Test with very short time range (1 second)"""
        log_content = """2024-01-01T10:15:30 Log 1
2024-01-01T10:15:31 Log 2
2024-01-01T10:15:32 Log 3"""
        start = datetime(2024, 1, 1, 10, 15, 30)
        end = datetime(2024, 1, 1, 10, 15, 31)
        result = slice_by_time(log_content, start, end)
        self.assertEqual(len(result), 2)  # Both at start and end

    def test_very_long_time_range(self):
        """Test with very long time range"""
        log_content = """2024-01-01T10:15:00 Log 1
2024-01-02T15:30:00 Log 2
2024-01-03T20:45:00 Log 3"""
        start = datetime(2024, 1, 1, 0, 0, 0)
        end = datetime(2024, 1, 4, 0, 0, 0)
        result = slice_by_time(log_content, start, end)
        self.assertEqual(len(result), 3)

    def test_cross_year_boundary(self):
        """Test time range crossing year boundary"""
        log_content = """2023-12-31T23:59:00 Last year log
2024-01-01T00:01:00 New year log"""
        start = datetime(2023, 12, 31, 23, 59, 0)
        end = datetime(2024, 1, 1, 0, 1, 0)
        result = slice_by_time(log_content, start, end)
        self.assertEqual(len(result), 2)

    # ========== File Output Tests ==========
    
    def test_slice_by_time_to_file_temp_file(self):
        """Test slice_by_time_to_file creates a temporary file"""
        log_content = """2024-01-01T09:30:00 Early log
2024-01-01T10:15:00 Middle log
2024-01-01T10:45:00 Later log
2024-01-01T11:30:00 Late log"""
        
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        # Verify file exists
        self.assertTrue(os.path.exists(output_file))
        
        # Verify file extension
        self.assertTrue(output_file.endswith('.log'))
        
        # Verify file content
        with open(output_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("2024-01-01T10:15:00 Middle log", lines)
            self.assertIn("2024-01-01T10:45:00 Later log", lines)
            self.assertNotIn("2024-01-01T09:30:00 Early log", lines)
            self.assertNotIn("2024-01-01T11:30:00 Late log", lines)

    def test_slice_by_time_to_file_specified_file(self):
        """Test slice_by_time_to_file writes to specified file path"""
        log_content = """2024-01-01T10:15:00 Log 1
2024-01-01T10:30:00 Log 2"""
        
        # Create output file in temp directory
        output_path = os.path.join(tempfile.gettempdir(), 'test_filtered.log')
        self.temp_files.append(output_path)
        
        result_path = slice_by_time_to_file(
            log_content, 
            self.test_start_time, 
            self.test_end_time, 
            output_file=output_path
        )
        
        # Verify correct path returned
        self.assertEqual(result_path, output_path)
        
        # Verify file exists
        self.assertTrue(os.path.exists(output_path))
        
        # Verify file content
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("2024-01-01T10:15:00 Log 1", content)
            self.assertIn("2024-01-01T10:30:00 Log 2", content)

    def test_slice_by_time_to_file_with_file_input(self):
        """Test slice_by_time_to_file with file path as input"""
        log_content = """2024-01-01T09:30:00 Early log
2024-01-01T10:15:00 Middle log
2024-01-01T10:45:00 Later log"""
        
        input_file = self._create_temp_log_file(log_content)
        output_file = slice_by_time_to_file(input_file, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        # Verify output file exists
        self.assertTrue(os.path.exists(output_file))
        
        # Verify content
        with open(output_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)

    def test_slice_by_time_to_file_empty_result(self):
        """Test slice_by_time_to_file with no matching logs"""
        log_content = """2024-01-01T08:00:00 Early log
2024-01-01T12:00:00 Late log"""
        
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        # File should still be created
        self.assertTrue(os.path.exists(output_file))
        
        # File should be empty
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertEqual(content, "")

    def test_slice_by_time_to_file_directory_creation(self):
        """Test slice_by_time_to_file creates file in specified directory"""
        log_content = """2024-01-01T10:15:00 Test log"""
        
        # Create a temp directory
        temp_dir = tempfile.mkdtemp()
        self.temp_files.append(temp_dir)  # Will be cleaned up
        
        output_path = os.path.join(temp_dir, 'filtered', 'output.log')
        self.temp_files.append(output_path)
        
        # Create parent directory first (function doesn't create directories)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        result_path = slice_by_time_to_file(
            log_content,
            self.test_start_time,
            self.test_end_time,
            output_file=output_path
        )
        
        # Verify file exists
        self.assertTrue(os.path.exists(output_path))
        self.assertEqual(result_path, output_path)
        
        # Clean up directory
        import shutil
        try:
            shutil.rmtree(temp_dir)
        except:
            pass

    def test_slice_by_time_to_file_relative_path(self):
        """Test slice_by_time_to_file with relative file path"""
        log_content = """2024-01-01T10:15:00 Test log"""
        
        # Use relative path in temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            original_dir = os.getcwd()
            try:
                os.chdir(temp_dir)
                output_file = 'relative_output.log'
                self.temp_files.append(os.path.join(temp_dir, output_file))
                
                result_path = slice_by_time_to_file(
                    log_content,
                    self.test_start_time,
                    self.test_end_time,
                    output_file=output_file
                )
                
                # Verify file exists
                self.assertTrue(os.path.exists(output_file))
                self.assertEqual(result_path, output_file)
            finally:
                os.chdir(original_dir)

    def test_slice_by_time_to_file_file_content_verification(self):
        """Test that file content matches filtered results exactly"""
        log_content = """2024-01-01T10:15:00 First log
2024-01-01T10:30:00 Second log
2024-01-01T10:45:00 Third log"""
        
        # Get list result
        list_result = slice_by_time(log_content, self.test_start_time, self.test_end_time)
        
        # Get file result
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        # Read file content
        with open(output_file, 'r', encoding='utf-8') as f:
            file_lines = f.read().splitlines()
        
        # Compare results
        self.assertEqual(len(list_result), len(file_lines))
        for i, line in enumerate(list_result):
            self.assertEqual(line, file_lines[i])

    def test_slice_by_time_to_file_preserves_line_order(self):
        """Test that file output preserves the original line order"""
        log_content = """2024-01-01T09:30:00 Before range
2024-01-01T10:15:00 First in range
2024-01-01T10:30:00 Second in range
2024-01-01T10:45:00 Third in range
2024-01-01T11:30:00 After range"""
        
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        with open(output_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        
        # Verify order - should have exactly 3 lines in range
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("2024-01-01T10:15:00"))
        self.assertTrue(lines[1].startswith("2024-01-01T10:30:00"))
        self.assertTrue(lines[2].startswith("2024-01-01T10:45:00"))

    def test_slice_by_time_to_file_temp_file_location(self):
        """Test that temporary file is created in system temp directory"""
        log_content = """2024-01-01T10:15:00 Test log"""
        
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        # Verify file exists
        self.assertTrue(os.path.exists(output_file))
        
        # Verify it's in a temp directory (or at least a valid path)
        self.assertTrue(os.path.isabs(output_file) or output_file.startswith('/tmp'))
        
        # Verify file has .log extension
        self.assertTrue(output_file.endswith('.log'))

    def test_slice_by_time_to_file_with_list_input(self):
        """Test slice_by_time_to_file with list of lines as input"""
        log_content = [
            "2024-01-01T09:30:00 Early log",
            "2024-01-01T10:15:00 Middle log",
            "2024-01-01T10:45:00 Later log"
        ]
        
        output_file = slice_by_time_to_file(log_content, self.test_start_time, self.test_end_time)
        self.temp_files.append(output_file)
        
        self.assertTrue(os.path.exists(output_file))
        with open(output_file, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)


if __name__ == '__main__':
    unittest.main()

