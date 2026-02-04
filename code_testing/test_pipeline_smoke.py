"""
Pipeline Smoke Test

Calls verify_pipeline.py and asserts exit code == 0.
Fast test (<10 seconds) using sample.log.
"""

import unittest
import subprocess
import sys
import os
from pathlib import Path


class TestPipelineSmoke(unittest.TestCase):
    """Smoke test for pipeline verification."""
    
    def setUp(self):
        """Set up test environment."""
        self.project_root = Path(__file__).parent.parent
        self.verify_script = self.project_root / "scripts" / "verify_pipeline.py"
        
    def test_pipeline_verification(self):
        """Test that verify_pipeline.py exits with code 0."""
        self.assertTrue(
            self.verify_script.exists(),
            f"Verification script not found: {self.verify_script}"
        )
        
        # Run verification script
        result = subprocess.run(
            [sys.executable, str(self.verify_script)],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
            timeout=60  # Allow up to 60 seconds
        )
        
        # Print output for debugging
        if result.stdout:
            print("\n" + "="*60)
            print("VERIFICATION OUTPUT")
            print("="*60)
            print(result.stdout)
        
        if result.stderr:
            print("\n" + "="*60)
            print("VERIFICATION ERRORS")
            print("="*60)
            print(result.stderr)
        
        # Assert exit code is 0
        self.assertEqual(
            result.returncode,
            0,
            f"Verification script failed with exit code {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
