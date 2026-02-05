"""
Reporter Agent

Writes final answer from investigation findings.
Produces a markdown report saved to final_answer.md.
"""

from __future__ import annotations

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from agent.llm.ollama_client import OllamaClient
except ImportError:
    OllamaClient = None


class ReporterAgent:
    """Agent responsible for writing the final answer report."""

    def generate_report(
        self,
        query: str,
        retrieval_results: Dict[str, Any],
        investigation_findings: Dict[str, Any],
        job_id: Optional[str] = None,
    ) -> str:
        """
        Generate final answer report from retrieval and investigation results.

        Uses Ollama LLM to generate a markdown report based on the findings.

        Args:
            query: Original user query.
            retrieval_results: Results from retrieval agent.
            investigation_findings: Findings from investigation agent.
            job_id: Optional job ID for reference.

        Returns:
            Markdown-formatted report string.
        """
        if OllamaClient is None:
            # Fallback to template-based report if Ollama is not available
            return self._generate_template_report(query, retrieval_results, investigation_findings, job_id)

        try:
            model = os.getenv("LLAMA_MODEL", "llama3")
            client = OllamaClient(model=model)

            # Prepare findings data for LLM
            findings_json = json.dumps(investigation_findings, indent=2)
            retrieval_summary = json.dumps({
                "chunks_retrieved": retrieval_results.get("chunks_retrieved", 0),
                "chunks_indexed": retrieval_results.get("chunks_indexed", 0),
            }, indent=2)

            prompt = f"""You are a technical report writer for log analysis. Generate a comprehensive markdown report based on the investigation findings.

User Query: {query}
Job ID: {job_id or "N/A"}

Investigation Findings:
{findings_json}

Retrieval Summary:
{retrieval_summary}

Generate a markdown report with the following structure:
1. **Header**: Title "Log Analysis Report", Job ID (if provided), Query, and Generation timestamp
2. **Executive Summary**: Brief overview of the analysis
3. **Root Causes**: List of identified root causes (if any)
4. **Key Findings**: Detailed findings including error sequences and patterns
5. **Timeline**: Chronological events (if available)
6. **Recommendations**: Actionable recommendations based on findings

Requirements:
- Use pure Markdown formatting
- Be clear, concise, and technical
- Include all relevant details from the findings
- Structure the report professionally
- Do NOT include any tool calls or code execution logic
- Focus on analysis and insights

Output ONLY the markdown report, no explanations or additional text."""

            messages = [
                {
                    "role": "system",
                    "content": "You are a technical report writer. Generate clear, structured markdown reports based on log analysis findings."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            report = client.chat(messages=messages, temperature=0.3)
            return report.strip()

        except Exception as exc:
            # Fallback to template-based report on error
            return self._generate_template_report(query, retrieval_results, investigation_findings, job_id)

    def _generate_template_report(
        self,
        query: str,
        retrieval_results: Dict[str, Any],
        investigation_findings: Dict[str, Any],
        job_id: Optional[str] = None,
    ) -> str:
        """
        Fallback template-based report generation.

        Args:
            query: Original user query.
            retrieval_results: Results from retrieval agent.
            investigation_findings: Findings from investigation agent.
            job_id: Optional job ID for reference.

        Returns:
            Markdown-formatted report string.
        """
        report_lines = []

        # Header
        report_lines.append("# Log Analysis Report")
        report_lines.append("")
        if job_id:
            report_lines.append(f"**Job ID:** {job_id}")
            report_lines.append("")
        report_lines.append(f"**Query:** {query}")
        report_lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

        # Executive Summary
        report_lines.append("## Executive Summary")
        report_lines.append("")
        summary = investigation_findings.get("summary", "No summary available.")
        report_lines.append(summary)
        report_lines.append("")

        # Retrieval Summary
        chunks_retrieved = retrieval_results.get("chunks_retrieved", 0)
        chunks_indexed = retrieval_results.get("chunks_indexed", 0)
        report_lines.append(f"**Evidence Retrieved:** {chunks_retrieved} relevant chunks from {chunks_indexed} indexed chunks")
        report_lines.append("")

        # Root Causes
        root_causes = investigation_findings.get("root_causes", [])
        if root_causes:
            report_lines.append("## Root Causes")
            report_lines.append("")
            for i, cause in enumerate(root_causes, 1):
                report_lines.append(f"{i}. {cause}")
            report_lines.append("")

        # Key Findings
        findings = investigation_findings.get("findings", [])
        if findings:
            report_lines.append("## Key Findings")
            report_lines.append("")

            # Group findings by type
            error_sequences = [f for f in findings if f.get("type") == "error_sequence"]
            patterns = [f for f in findings if f.get("type") == "pattern"]

            if error_sequences:
                report_lines.append("### Error Sequences")
                report_lines.append("")
                for i, seq in enumerate(error_sequences[:5], 1):  # Top 5
                    report_lines.append(f"#### Sequence {i}")
                    report_lines.append(f"- **Description:** {seq.get('description', 'N/A')}")
                    if seq.get("error_codes"):
                        report_lines.append(f"- **Error Codes:** {', '.join(seq['error_codes'])}")
                    if seq.get("services"):
                        report_lines.append(f"- **Services:** {', '.join(seq['services'])}")
                    report_lines.append(f"- **Severity:** {seq.get('severity', 'unknown')}")
                    report_lines.append("")

            if patterns:
                report_lines.append("### Patterns Detected")
                report_lines.append("")
                for pattern in patterns[:5]:  # Top 5
                    report_lines.append(f"- **{pattern.get('pattern', 'N/A')}**: {pattern.get('frequency', 0)} occurrences")
                report_lines.append("")

        # Timeline
        timeline = investigation_findings.get("timeline", [])
        if timeline:
            report_lines.append("## Timeline")
            report_lines.append("")
            report_lines.append("| Timestamp | Service | Log Level | Event |")
            report_lines.append("|-----------|---------|-----------|-------|")
            for event in timeline[:20]:  # Top 20 events
                timestamp = event.get("timestamp", "N/A")
                service = event.get("service", "N/A")
                log_level = event.get("log_level", "N/A")
                preview = event.get("content_preview", "N/A")[:100]
                report_lines.append(f"| {timestamp} | {service} | {log_level} | {preview} |")
            report_lines.append("")

        # Recommendations
        report_lines.append("## Recommendations")
        report_lines.append("")
        if root_causes:
            report_lines.append("Based on the investigation:")
            report_lines.append("")
            for i, cause in enumerate(root_causes[:3], 1):  # Top 3
                recommendation = self._generate_recommendation(cause)
                report_lines.append(f"{i}. {recommendation}")
        else:
            report_lines.append("No specific recommendations at this time.")
        report_lines.append("")

        # Footer
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("*Report generated by Log Analysis AI Agent*")

        return "\n".join(report_lines)

    def _generate_recommendation(self, root_cause: str) -> str:
        """Generate recommendation based on root cause."""
        root_cause_lower = root_cause.lower()

        if "timeout" in root_cause_lower:
            return "Review network latency, increase timeout values, or optimize slow queries."
        elif "connection" in root_cause_lower:
            return "Check database/service connectivity, verify connection pool settings, and review firewall rules."
        elif "retry" in root_cause_lower:
            return "Investigate transient failures, consider implementing exponential backoff, or review upstream service health."
        elif "error code" in root_cause_lower:
            return "Review error code documentation, check service-specific error handling, and verify system configuration."
        else:
            return "Review logs for additional context and consider escalating to relevant service owners."

    def save_report(
        self, report: str, output_path: str
    ) -> str:
        """
        Save final answer report to markdown file.

        Args:
            report: Markdown report string.
            output_path: Path to save final_answer.md.

        Returns:
            Path to saved file.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return output_path
