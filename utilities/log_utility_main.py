try:
    from .search_on_keyword import search_keyword
except ImportError:
    from search_on_keyword import search_keyword
try:
    from .filter_log_level import (
        filter_by_log_level,
        filter_by_log_level_to_file,
        interactive_filter_by_log_level
    )
    from .log_summary import (
        summarize_log,
        format_summary,
        summarize_log_to_file,
        LogSummary,
        ErrorCodeInfo,
        StacktraceInfo
    )
    from .stacktrace import (
        extract_stacktraces,
        extract_stacktraces_to_files,
        format_stacktrace_summary,
        Stacktrace,
        StacktraceSummary
    )
    from .time_slice import (
        slice_by_time,
        slice_by_time_range
    )
    from .error_code import (
        search_by_error_code,
        extract_all_error_codes,
        search_by_error_code_to_file,
        interactive_search_by_error_code,
        format_error_code_summary,
        ErrorCodeMatch,
        ErrorCodeSummary
    )
    from .error_lines import get_error_lines
except ImportError:
    from filter_log_level import (
        filter_by_log_level,
        filter_by_log_level_to_file,
        interactive_filter_by_log_level
    )
    from log_summary import (
        summarize_log,
        format_summary,
        summarize_log_to_file,
        LogSummary,
        ErrorCodeInfo,
        StacktraceInfo
    )
    from stacktrace import (
        extract_stacktraces,
        extract_stacktraces_to_files,
        format_stacktrace_summary,
        Stacktrace,
        StacktraceSummary
    )
    from time_slice import (
        slice_by_time,
        slice_by_time_range
    )
    from error_code import (
        search_by_error_code,
        extract_all_error_codes,
        search_by_error_code_to_file,
        interactive_search_by_error_code,
        format_error_code_summary,
        ErrorCodeMatch,
        ErrorCodeSummary
    )
    from error_lines import get_error_lines

# Standard library imports
import os
import sys
import tempfile
from datetime import datetime


# Export all functions and classes for easy access
__all__ = [
    # Search utilities
    'search_keyword',
    
    # Filter utilities
    'filter_by_log_level',
    'filter_by_log_level_to_file',
    'interactive_filter_by_log_level',
    
    # Log summary utilities
    'summarize_log',
    'format_summary',
    'summarize_log_to_file',
    'LogSummary',
    'ErrorCodeInfo',
    'StacktraceInfo',
    
    # Stacktrace utilities
    'extract_stacktraces',
    'extract_stacktraces_to_files',
    'format_stacktrace_summary',
    'Stacktrace',
    'StacktraceSummary',
    
    # Time slice utilities
    'slice_by_time',
    'slice_by_time_range',
    
    # Error code utilities
    'search_by_error_code',
    'extract_all_error_codes',
    'search_by_error_code_to_file',
    'interactive_search_by_error_code',
    'format_error_code_summary',
    'ErrorCodeMatch',
    'ErrorCodeSummary',
    
    # Error lines utilities
    'get_error_lines',
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
        
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            log_content = f.read()
        
        result_file = search_keyword(log_content, keywords)
        print(f"\n✓ Results saved to: {result_file}")
    
    elif choice == "2":
        # Filter by Log Level
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            result_files = interactive_filter_by_log_level(log_file)
            if result_files:
                print("\n✓ Filtering complete!")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "3":
        # Log Summary
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            output_file = summarize_log_to_file(log_file)
            print(f"\n✓ Summary saved to: {output_file}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "4":
        # Extract Stacktraces
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            result_files = extract_stacktraces_to_files(log_file)
            print("\n✓ Stacktrace extraction complete!")
            print(f"  Clean log: {result_files['clean_log']}")
            print(f"  Stacktraces: {result_files['stacktraces']}")
            print(f"  Summary: {result_files['summary']}")
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "5":
        # Time Slice
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        start_str = input("Enter start time (YYYY-MM-DD HH:MM:SS): ").strip()
        end_str = input("Enter end time (YYYY-MM-DD HH:MM:SS): ").strip()
        
        try:
            start_time = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.strptime(end_str, '%Y-%m-%d %H:%M:%S')
            
            filtered_lines = slice_by_time(log_file, start_time, end_time)
            print(f"\n✓ Found {len(filtered_lines)} lines in the specified time range")
            
            save = input("Save to file? (y/n): ").strip().lower()
            if save == 'y':
                temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log', encoding='utf-8')
                temp_file.write('\n'.join(filtered_lines))
                temp_file.close()
                print(f"  Saved to: {temp_file.name}")
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
        
        try:
            interactive_search_by_error_code(log_file)
        except Exception as e:
            print(f"Error: {e}")
    
    elif choice == "7":
        # Get Error Lines
        log_file = input("Enter log file path: ").strip()
        
        if not os.path.isfile(log_file):
            print(f"Error: File not found: {log_file}")
            return
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                log_content = f.read()
            
            error_lines = get_error_lines(log_content)
            print(f"\n✓ Found {len(error_lines)} error lines")
            
            if error_lines:
                for line in error_lines[:10]:  # Show first 10
                    print(f"  {line}")
                if len(error_lines) > 10:
                    print(f"  ... and {len(error_lines) - 10} more")
        except Exception as e:
            print(f"Error: {e}")
    
    else:
        print("Invalid choice. Please enter a number between 0-7.")


if __name__ == "__main__":
    main()

