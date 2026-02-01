try:
    from .search_on_keyword import search_keyword, run_search_keyword
except ImportError:
    from search_on_keyword import search_keyword, run_search_keyword
try:
    from .filter_log_level import (
        filter_by_log_level,
        filter_by_log_level_to_file,
        interactive_filter_by_log_level,
        run_filter_log_level
    )
    from .log_summary import (
        summarize_log,
        format_summary,
        summarize_log_to_file,
        LogSummary,
        ErrorCodeInfo,
        StacktraceInfo,
        run_log_summary
    )
    from .stacktrace import (
        extract_stacktraces,
        extract_stacktraces_to_files,
        format_stacktrace_summary,
        Stacktrace,
        StacktraceSummary,
        run_stacktrace
    )
    from .time_slice import (
        slice_by_time,
        slice_by_time_range,
        slice_by_time_to_file,
        interactive_slice_by_time,
        run_time_slice
    )
    from .error_code import (
        search_by_error_code,
        extract_all_error_codes,
        search_by_error_code_to_file,
        interactive_search_by_error_code,
        format_error_code_summary,
        ErrorCodeMatch,
        ErrorCodeSummary,
        run_error_code_search,
        run_error_code_extract_all
    )
    from .error_lines import get_error_lines, run_error_lines
except ImportError:
    from filter_log_level import (
        filter_by_log_level,
        filter_by_log_level_to_file,
        interactive_filter_by_log_level,
        run_filter_log_level
    )
    from log_summary import (
        summarize_log,
        format_summary,
        summarize_log_to_file,
        LogSummary,
        ErrorCodeInfo,
        StacktraceInfo,
        run_log_summary
    )
    from stacktrace import (
        extract_stacktraces,
        extract_stacktraces_to_files,
        format_stacktrace_summary,
        Stacktrace,
        StacktraceSummary,
        run_stacktrace
    )
    from time_slice import (
        slice_by_time,
        slice_by_time_range,
        slice_by_time_to_file,
        interactive_slice_by_time,
        run_time_slice
    )
    from error_code import (
        search_by_error_code,
        extract_all_error_codes,
        search_by_error_code_to_file,
        interactive_search_by_error_code,
        format_error_code_summary,
        ErrorCodeMatch,
        ErrorCodeSummary,
        run_error_code_search,
        run_error_code_extract_all
    )
    from error_lines import get_error_lines, run_error_lines

# Standard library imports
import os
import sys
import tempfile
from datetime import datetime


# Export all functions and classes for easy access
__all__ = [
    # Search utilities
    'search_keyword',
    'run_search_keyword',
    
    # Filter utilities
    'filter_by_log_level',
    'filter_by_log_level_to_file',
    'interactive_filter_by_log_level',
    'run_filter_log_level',
    
    # Log summary utilities
    'summarize_log',
    'format_summary',
    'summarize_log_to_file',
    'run_log_summary',
    'LogSummary',
    'ErrorCodeInfo',
    'StacktraceInfo',
    
    # Stacktrace utilities
    'extract_stacktraces',
    'extract_stacktraces_to_files',
    'format_stacktrace_summary',
    'run_stacktrace',
    'Stacktrace',
    'StacktraceSummary',
    
    # Time slice utilities
    'slice_by_time',
    'slice_by_time_range',
    'slice_by_time_to_file',
    'interactive_slice_by_time',
    'run_time_slice',
    
    # Error code utilities
    'search_by_error_code',
    'extract_all_error_codes',
    'search_by_error_code_to_file',
    'interactive_search_by_error_code',
    'format_error_code_summary',
    'run_error_code_search',
    'run_error_code_extract_all',
    'ErrorCodeMatch',
    'ErrorCodeSummary',
    
    # Error lines utilities
    'get_error_lines',
    'run_error_lines',
]


def main():
    """
    Main function that provides a menu-driven interface to access all log analysis utilities.
    """
    print("="*70)
    print("LOG ANALYSIS UTILITIES - Main Menu")
    print("="*70)
    print("\nAvailable utilities:")
    print("-"*70)
    print("1. Search by Keyword")
    print("2. Filter by Log Level")
    print("3. Log Summary")
    print("4. Extract Stacktraces")
    print("5. Time Slice")
    print("6. Search by Error Code")
    print("7. Get Error Lines")
    print("0. Exit")
    print("-"*70)
    
    choice = input("\nEnter your choice (0-7): ").strip()
    
    if choice == "0":
        print("Exiting...")
        sys.exit(0)
    
    elif choice == "1":
        # Search by Keyword
        log_file = input("Enter log file path: ").strip()
        keyword = input("Enter keyword(s) to search (comma-separated for multiple): ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        keywords = [k.strip() for k in keyword.split(',')] if ',' in keyword else keyword
        
        result = run_search_keyword(log_file, keywords)
        
        if result["success"]:
            print(f"\n✓ Found {result['match_count']} matching lines")
            if result["output_file"]:
                print(f"✓ Results saved to: {result['output_file']}")
        else:
            print(f"✗ Error: {result['error']}")
    
    elif choice == "2":
        # Filter by Log Level
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        print("\nAvailable log levels: ERROR, FATAL, CRITICAL, WARN, WARNING, INFO, DEBUG, TRACE")
        levels_input = input("Enter log level(s) to filter (comma-separated): ").strip()
        
        if not levels_input:
            print("No log levels provided.")
            return
        
        log_levels = [l.strip().upper() for l in levels_input.split(',')]
        
        try:
            result = run_filter_log_level(log_file, log_levels)
            
            if result["success"]:
                print(f"\n✓ Filtered {len(result['filtered_lines'])} lines")
                for level, count in result["counts_by_level"].items():
                    print(f"  {level}: {count} lines")
                if result["output_files"]:
                    print(f"\n✓ Created {len(result['output_files'])} output file(s)")
                    for output_file in result["output_files"]:
                        print(f"  - {output_file}")
            else:
                print(f"✗ Error: {result['error']}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "3":
        # Log Summary
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            result = run_log_summary(log_file)
            
            if result["success"]:
                print("\n" + result["formatted_summary"])
                if result["output_file"]:
                    print(f"\n✓ Summary saved to: {result['output_file']}")
            else:
                print(f"✗ Error: {result['error']}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "4":
        # Extract Stacktraces
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            result = run_stacktrace(log_file)
            
            if result["success"]:
                print("\n" + result["formatted_summary"])
                if result["output_files"]["clean_log"]:
                    print(f"\n✓ Clean log: {result['output_files']['clean_log']}")
                if result["output_files"]["stacktraces"]:
                    print(f"✓ Stacktraces: {result['output_files']['stacktraces']}")
                if result["output_files"]["summary"]:
                    print(f"✓ Summary: {result['output_files']['summary']}")
            else:
                print(f"✗ Error: {result['error']}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "5":
        # Time Slice
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            start_time = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
            
            result = run_time_slice(log_file, start_time, end_time)
            
            if result["success"]:
                print(f"\n✓ Found {result['lines_found']} lines in the specified time range")
                if result["output_file"]:
                    print(f"✓ Results saved to: {result['output_file']}")
            else:
                print(f"✗ Error: {result['error']}")
        except ValueError as e:
            print(f"Error: Invalid time format. Use YYYY-MM-DD HH:MM:SS. {e}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "6":
        # Search by Error Code
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        print("\nOptions:")
        print("1. Search for specific error code(s)")
        print("2. Extract all error codes")
        sub_choice = input("Enter choice (1 or 2): ").strip()
        
        try:
            if sub_choice == "1":
                codes_input = input("Enter error code(s) to search (comma-separated): ").strip()
                if not codes_input:
                    print("No error codes provided.")
                    return
                
                error_codes = [c.strip() for c in codes_input.split(',')]
                result = run_error_code_search(log_file, error_codes)
                
                if result["success"]:
                    print(f"\n✓ Found {len(result['matched_lines'])} matching lines")
                    for code, count in result["counts_by_code"].items():
                        print(f"  {code}: {count} occurrences")
                    if result["output_file"]:
                        print(f"✓ Results saved to: {result['output_file']}")
                else:
                    print(f"✗ Error: {result['error']}")
            
            elif sub_choice == "2":
                result = run_error_code_extract_all(log_file)
                
                if result["success"]:
                    print("\n" + result["formatted_summary"])
                    if result["summary_file"]:
                        print(f"\n✓ Summary saved to: {result['summary_file']}")
                else:
                    print(f"✗ Error: {result['error']}")
            else:
                print("Invalid choice.")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "7":
        # Get Error Lines
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            result = run_error_lines(log_file)
            
            if result["success"]:
                print(f"\n✓ Found {result['error_count']} error lines")
                
                if result["error_lines"]:
                    for line in result["error_lines"][:10]:  # Show first 10
                        print(f"  {line}")
                    if len(result["error_lines"]) > 10:
                        print(f"  ... and {len(result['error_lines']) - 10} more")
                
                if result["output_file"]:
                    print(f"\n✓ Results saved to: {result['output_file']}")
            else:
                print(f"✗ Error: {result['error']}")
        except Exception as e:
            print(f"Error: {e}")
    
    else:
        print("Invalid choice. Please enter a number between 0-7.")


if __name__ == "__main__":
    main()

