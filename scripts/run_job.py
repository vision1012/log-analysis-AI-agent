#!/usr/bin/env python3
"""
CLI Entrypoint for Running Log Analysis Jobs

Usage:
    python scripts/run_job.py --file data/sample.log --query "Show me all errors"
    python scripts/run_job.py --file data/sample.log --query "Analyze this log" --mode llm
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.runtime.job_models import JobRequest
from agent.runtime.worker import run_job


def main():
    """Parse CLI arguments and run the job."""
    parser = argparse.ArgumentParser(
        description="Run a log analysis job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file",
        type=str,
        required=True,
        help="Path to the log file to analyze",
    )
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="Natural language query or instruction",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["heuristic", "llm"],
        default="heuristic",
        help="Planning mode: heuristic (rule-based) or llm (LLM-based). Default: heuristic",
    )

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    request = JobRequest(
        query=args.query,
        file_paths=[str(file_path.absolute())],
    )

    try:
        result = run_job(request, mode=args.mode)

        print("=" * 70)
        print("JOB RESULT")
        print("=" * 70)
        print(f"Job ID: {result.job_id}")
        print(f"Status: {result.status}")
        print()

        # Print directory paths (absolute paths for observability)
        import os
        job_dir = os.path.join("output", "jobs", result.job_id)
        job_dir_abs = os.path.abspath(job_dir)
        artifacts_dir_abs = os.path.abspath(os.path.join(job_dir, "artifacts"))
        tool_results_dir_abs = os.path.abspath(os.path.join(job_dir, "tool_results"))
        
        print("Directory Paths:")
        print(f"  Job Directory:      {job_dir_abs}")
        print(f"  Artifacts Directory: {artifacts_dir_abs}")
        print(f"  Tool Results Dir:   {tool_results_dir_abs}")
        print()

        if result.final_answer:
            print("Final Answer:")
            print("-" * 70)
            print(result.final_answer)
            print()

        if result.artifacts:
            print("Generated Artifacts:")
            for artifact in result.artifacts:
                print(f"  - {artifact.name}: {artifact.path}")
            print()

        if result.errors:
            print("Errors:")
            for error in result.errors:
                print(f"  ✗ {error}")
            print()

        if result.warnings:
            print("Warnings:")
            for warning in result.warnings:
                print(f"  ⚠ {warning}")
            print()

        if result.timing.duration_ms is not None:
            print(f"Duration: {result.timing.duration_ms}ms")
            print()

        print(f"Full job state saved to: {os.path.join(job_dir_abs, 'job.json')}")

        sys.exit(0 if result.status == "succeeded" else 1)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
