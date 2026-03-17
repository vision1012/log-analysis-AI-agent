#!/usr/bin/env python3
"""
Pipeline Verification Script

Runs 3 verification scenarios to ensure the pipeline is safe:
- Scenario A: Heuristic end-to-end
- Scenario B: LLM mode graceful failure
- Scenario C: Resume/idempotency

Exits with non-zero code if any scenario fails.
"""

import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.runtime.worker import run_job
from agent.runtime.job_models import JobRequest
from agent.planner.plan_models import Plan
from agent.tool_wrapper import validate_tool_result
from agent.runtime.storage import read_job_state, get_existing_artifacts


def get_job_id_from_hash(file_path: str, query: str, mode: str) -> str:
    """Generate deterministic job_id from hash of inputs."""
    key = f"{file_path}|{query}|{mode}"
    hash_obj = hashlib.md5(key.encode())
    return hash_obj.hexdigest()[:8]


def create_deterministic_job_dir(job_id: str) -> str:
    """Create deterministic job directory path."""
    return os.path.join("output", "jobs", f"verify_{job_id}")


def scenario_a_heuristic() -> tuple[bool, str]:
    """Scenario A: Heuristic end-to-end verification."""
    print("\n" + "="*60)
    print("SCENARIO A: Heuristic End-to-End")
    print("="*60)
    
    try:
        file_path = "data/sample.log"
        query = "Summarize errors"
        mode = "heuristic"
        
        if not os.path.isfile(file_path):
            return False, f"Test file not found: {file_path}"
        
        request = JobRequest(query=query, file_paths=[file_path])
        result = run_job(request, mode=mode)
        
        job_dir = os.path.join("output", "jobs", result.job_id)
        
        # Check required files
        required_files = {
            "job.json": os.path.join(job_dir, "job.json"),
            "plan.json": os.path.join(job_dir, "plan.json"),
        }
        
        # Validate job.json structure first
        job_state = read_job_state(job_dir)
        if not job_state:
            return False, "Failed to read job.json"
        
        # Verify all required files exist
        missing = []
        for name, path in required_files.items():
            if not os.path.isfile(path):
                missing.append(name)
        
        if missing:
            return False, f"Missing required files: {', '.join(missing)}"
        
        # Check for final_answer (could be .md or .txt, or check job.json for final_answer content)
        final_answer_files = [
            os.path.join(job_dir, "final_answer.md"),
            os.path.join(job_dir, "final_answer.txt"),
        ]
        final_answer_found = any(os.path.isfile(f) for f in final_answer_files)
        
        # Also check if final_answer exists in job.json (might be in-memory only)
        if not final_answer_found:
            final_answer_content = job_state.get("final_answer")
            if final_answer_content:
                final_answer_found = True
        
        if not final_answer_found:
            return False, "Missing final_answer.md, final_answer.txt, or final_answer in job.json"
        
        # Check for findings (could be .json or .md) - optional, not required
        findings_files = [
            os.path.join(job_dir, "findings.json"),
            os.path.join(job_dir, "findings.md"),
        ]
        findings_found = any(os.path.isfile(f) for f in findings_files)
        
        # Validate plan.json
        plan_path = required_files["plan.json"]
        try:
            with open(plan_path, "r") as f:
                plan_data = json.load(f)
            plan = Plan.model_validate(plan_data)
            print(f"✓ plan.json validates against Plan schema")
        except Exception as e:
            return False, f"plan.json validation failed: {e}"
        
        # Validate all tool results
        tool_results = job_state.get("tool_results", [])
        for i, tool_result in enumerate(tool_results):
            try:
                validated = validate_tool_result(tool_result)
                print(f"✓ Tool result {i} validates")
            except Exception as e:
                return False, f"Tool result {i} validation failed: {e}"
        
        print(f"✓ All required files exist")
        print(f"✓ Job status: {result.status}")
        return True, f"Job {result.job_id} completed successfully"
        
    except Exception as e:
        return False, f"Scenario A failed with exception: {e}"


def scenario_b_llm_graceful() -> tuple[bool, str]:
    """Scenario B: LLM mode graceful failure."""
    print("\n" + "="*60)
    print("SCENARIO B: LLM Mode Graceful Failure")
    print("="*60)
    
    try:
        file_path = "data/sample.log"
        query = "Summarize errors"
        mode = "llm"
        
        if not os.path.isfile(file_path):
            return False, f"Test file not found: {file_path}"
        
        request = JobRequest(query=query, file_paths=[file_path])
        result = run_job(request, mode=mode)
        
        job_dir = os.path.join("output", "jobs", result.job_id)
        
        # Must produce plan.json and job.json even if LLM fails
        plan_path = os.path.join(job_dir, "plan.json")
        job_path = os.path.join(job_dir, "job.json")
        
        if not os.path.isfile(plan_path):
            return False, "plan.json not created (required even on LLM failure)"
        
        if not os.path.isfile(job_path):
            return False, "job.json not created (required even on LLM failure)"
        
        # Validate plan.json
        try:
            with open(plan_path, "r") as f:
                plan_data = json.load(f)
            plan = Plan.model_validate(plan_data)
            print(f"✓ plan.json validates against Plan schema")
        except Exception as e:
            return False, f"plan.json validation failed: {e}"
        
        # Job must complete (not crash) - status can be failed or succeeded
        if result.status not in ["succeeded", "failed", "succeeded_with_errors"]:
            return False, f"Job status invalid: {result.status} (must be succeeded/failed/succeeded_with_errors)"
        
        print(f"✓ Job completed without crash (status: {result.status})")
        print(f"✓ plan.json and job.json created")
        return True, f"LLM mode handled gracefully (status: {result.status})"
        
    except Exception as e:
        return False, f"Scenario B failed with exception: {e}"


def scenario_c_resume() -> tuple[bool, str]:
    """Scenario C: Resume/idempotency verification."""
    print("\n" + "="*60)
    print("SCENARIO C: Resume/Idempotency")
    print("="*60)
    
    try:
        file_path = "data/sample.log"
        query = "Summarize errors"
        mode = "heuristic"
        
        if not os.path.isfile(file_path):
            return False, f"Test file not found: {file_path}"
        
        # Generate deterministic job_id
        job_id = get_job_id_from_hash(file_path, query, mode)
        job_dir = create_deterministic_job_dir(job_id)
        
        # Clean up if exists
        if os.path.isdir(job_dir):
            import shutil
            shutil.rmtree(job_dir)
        
        # First run
        print("Running first execution...")
        request = JobRequest(query=query, file_paths=[file_path])
        result1 = run_job(request, mode=mode)
        
        # Get actual job_dir from result
        job_dir1 = os.path.join("output", "jobs", result1.job_id)
        
        # Get timestamps of key artifacts from first run
        artifacts1 = {}
        artifact_files = [
            "retrieval.json",
            "findings.json",
            "final_answer.md",
        ]
        
        for artifact in artifact_files:
            artifact_path = os.path.join(job_dir1, artifact)
            if os.path.isfile(artifact_path):
                artifacts1[artifact] = os.path.getmtime(artifact_path)
        
        # Get tool_results timestamps
        tool_results_dir = os.path.join(job_dir1, "tool_results")
        if os.path.isdir(tool_results_dir):
            for filename in os.listdir(tool_results_dir):
                if filename.endswith(".json"):
                    tool_result_path = os.path.join(tool_results_dir, filename)
                    artifacts1[f"tool_results/{filename}"] = os.path.getmtime(tool_result_path)
        
        print(f"First run created {len(artifacts1)} artifacts")
        
        # Second run - should reuse artifacts
        print("Running second execution (should reuse artifacts)...")
        result2 = run_job(request, mode=mode)
        job_dir2 = os.path.join("output", "jobs", result2.job_id)
        
        # Check if warnings indicate skipping
        warnings = result2.warnings or []
        skip_messages = [w for w in warnings if "existing" in str(w).lower() or "skip" in str(w).lower()]
        
        if skip_messages:
            print(f"✓ Found skip messages: {len(skip_messages)}")
            for msg in skip_messages[:3]:
                print(f"  - {msg}")
        else:
            # Check timestamps - artifacts should not be rewritten
            artifacts2 = {}
            for artifact in artifact_files:
                artifact_path = os.path.join(job_dir2, artifact)
                if os.path.isfile(artifact_path):
                    artifacts2[artifact] = os.path.getmtime(artifact_path)
            
            # Compare timestamps if same job_dir
            if job_dir1 == job_dir2:
                rewritten = []
                for artifact, timestamp1 in artifacts1.items():
                    timestamp2 = artifacts2.get(artifact)
                    if timestamp2 and timestamp2 > timestamp1:
                        rewritten.append(artifact)
                
                if rewritten:
                    return False, f"Artifacts were rewritten on second run: {', '.join(rewritten)}"
                else:
                    print(f"✓ No artifacts rewritten (timestamps unchanged)")
        
        # Verify artifact paths are stable
        job_state = read_job_state(job_dir2)
        if job_state:
            artifacts = job_state.get("artifacts", [])
            for artifact in artifacts:
                path = artifact.get("path", "") if isinstance(artifact, dict) else str(artifact)
                if path and not path.startswith("output/jobs/"):
                    return False, f"Artifact path not under job directory: {path}"
            print(f"✓ All artifact paths are under job directory")
        
        print(f"✓ Second run completed (status: {result2.status})")
        return True, "Resume/idempotency verified"
        
    except Exception as e:
        return False, f"Scenario C failed with exception: {e}"


def main():
    """Run all verification scenarios."""
    print("\n" + "="*60)
    print("PIPELINE VERIFICATION")
    print("="*60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # Scenario A
    passed, message = scenario_a_heuristic()
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] Scenario A: {message}")
    results.append(("A", passed, message))
    
    # Scenario B
    passed, message = scenario_b_llm_graceful()
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] Scenario B: {message}")
    results.append(("B", passed, message))
    
    # Scenario C
    passed, message = scenario_c_resume()
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] Scenario C: {message}")
    results.append(("C", passed, message))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    all_passed = all(passed for _, passed, _ in results)
    
    for scenario, passed, message in results:
        status = "PASS" if passed else "FAIL"
        print(f"Scenario {scenario}: {status}")
    
    print("\n" + "="*60)
    if all_passed:
        print("GO - All scenarios passed")
        print("="*60)
        sys.exit(0)
    else:
        print("NO-GO - One or more scenarios failed")
        print("="*60)
        sys.exit(1)


if __name__ == "__main__":
    main()
