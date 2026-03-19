"""
Tests for Planner Retrieval Auto-Trigger

Tests that planners correctly include run_retrieve_context for evidence-seeking queries
and exclude it for direct tool requests.
"""

import unittest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.runtime.job_models import JobRequest
from agent.planner.heuristic_planner import plan_heuristic
from agent.planner.plan_models import Plan


class TestPlannerRetrieval(unittest.TestCase):
    """Test that planners auto-trigger retrieval for appropriate queries."""

    def setUp(self):
        """Set up test fixtures."""
        self.file_path = "data/sample.log"
        self.available_tools = [
            "run_retrieve_context",
            "run_log_summary",
            "run_error_code_extract_all",
            "run_error_code_search",
            "run_stacktrace",
            "run_time_slice",
            "run_search_keyword",
            "run_filter_log_level",
            "run_error_lines",
        ]

    def _create_request(self, query: str) -> JobRequest:
        """Create a JobRequest for testing."""
        return JobRequest(query=query, file_paths=[self.file_path])

    def _has_retrieval_tool(self, tool_calls) -> bool:
        """Check if tool_calls includes run_retrieve_context."""
        return any(tc.name == "run_retrieve_context" for tc in tool_calls)

    def test_heuristic_why_query_triggers_retrieval(self):
        """Test that 'why' queries trigger retrieval."""
        request = self._create_request("why are timeouts happening?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls), 
                       "Why query should trigger retrieval")
        # Retrieval should be first
        self.assertEqual(tool_calls[0].name, "run_retrieve_context")

    def test_heuristic_what_happened_before_triggers_retrieval(self):
        """Test that 'what happened before' queries trigger retrieval."""
        request = self._create_request("what happened before the spike?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "What happened before query should trigger retrieval")

    def test_heuristic_root_cause_triggers_retrieval(self):
        """Test that 'root cause' queries trigger retrieval."""
        request = self._create_request("root cause of DB failures")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "Root cause query should trigger retrieval")

    def test_heuristic_correlation_triggers_retrieval(self):
        """Test that 'correlation' queries trigger retrieval."""
        request = self._create_request("correlation between errors and timeouts")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "Correlation query should trigger retrieval")

    def test_heuristic_analyze_triggers_retrieval(self):
        """Test that 'analyze' queries trigger retrieval."""
        request = self._create_request("analyze the failures")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "Analyze query should trigger retrieval")

    def test_heuristic_extract_all_error_codes_no_retrieval(self):
        """Test that direct 'extract all error codes' does NOT trigger retrieval."""
        request = self._create_request("extract all error codes")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertFalse(self._has_retrieval_tool(tool_calls),
                        "Direct extract request should NOT trigger retrieval")
        # Should have error code extraction tool instead
        self.assertTrue(any(tc.name == "run_error_code_extract_all" for tc in tool_calls))

    def test_heuristic_filter_by_level_no_retrieval(self):
        """Test that direct filter requests do NOT trigger retrieval."""
        request = self._create_request("filter by ERROR level")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertFalse(self._has_retrieval_tool(tool_calls),
                        "Direct filter request should NOT trigger retrieval")

    def test_heuristic_search_keyword_no_retrieval(self):
        """Test that direct search requests do NOT trigger retrieval."""
        request = self._create_request("search for keyword timeout")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertFalse(self._has_retrieval_tool(tool_calls),
                        "Direct search request should NOT trigger retrieval")

    def test_heuristic_time_slice_no_retrieval(self):
        """Test that direct time slice requests do NOT trigger retrieval."""
        request = self._create_request("time slice from 2025-01-12 to 2025-01-13")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertFalse(self._has_retrieval_tool(tool_calls),
                        "Direct time slice request should NOT trigger retrieval")

    def test_heuristic_retrieval_is_first(self):
        """Test that retrieval tool is placed first when triggered."""
        request = self._create_request("why are timeouts happening?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        if self._has_retrieval_tool(tool_calls):
            self.assertEqual(tool_calls[0].name, "run_retrieve_context",
                           "Retrieval should be first tool call")

    def test_heuristic_retrieval_has_correct_args(self):
        """Test that retrieval tool has correct arguments."""
        request = self._create_request("why are timeouts happening?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        retrieval_call = next((tc for tc in tool_calls if tc.name == "run_retrieve_context"), None)
        if retrieval_call:
            self.assertIn("file_path", retrieval_call.arguments)
            self.assertIn("query", retrieval_call.arguments)
            self.assertIn("top_k", retrieval_call.arguments)
            self.assertEqual(retrieval_call.arguments["top_k"], 8)

    def test_plan_validates_with_retrieval(self):
        """Test that Plan validates correctly when retrieval is included."""
        request = self._create_request("why are timeouts happening?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        # Create Plan and validate
        plan = Plan(
            mode="heuristic",
            tool_calls=tool_calls,
            reasoning="Test plan with retrieval",
        )
        
        # Should validate without errors
        self.assertEqual(plan.mode, "heuristic")
        self.assertGreater(len(plan.tool_calls), 0)
        self.assertTrue(self._has_retrieval_tool(plan.tool_calls))

    def test_heuristic_multiple_evidence_keywords(self):
        """Test that queries with multiple evidence keywords still trigger retrieval once."""
        request = self._create_request("why did the spike happen and what caused the failures?")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls))
        # Should only have one retrieval call
        retrieval_count = sum(1 for tc in tool_calls if tc.name == "run_retrieve_context")
        self.assertEqual(retrieval_count, 1, "Should have exactly one retrieval call")

    def test_heuristic_anomaly_detection_triggers_retrieval(self):
        """Test that anomaly detection queries trigger retrieval."""
        request = self._create_request("detect anomalies in the logs")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "Anomaly detection query should trigger retrieval")

    def test_heuristic_explain_pattern_triggers_retrieval(self):
        """Test that 'explain pattern' queries trigger retrieval."""
        request = self._create_request("explain the pattern of errors")
        tool_calls = plan_heuristic(request, self.available_tools)
        
        self.assertTrue(self._has_retrieval_tool(tool_calls),
                       "Explain pattern query should trigger retrieval")


if __name__ == "__main__":
    unittest.main()
