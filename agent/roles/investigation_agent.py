"""
Investigation Agent

Analyzes retrieved evidence to find patterns, sequences, and root causes.
Produces structured findings saved to findings.json.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict
from dateutil import parser as date_parser


class InvestigationAgent:
    """Agent responsible for investigating evidence and finding patterns."""

    def investigate(
        self,
        query: str,
        retrieval_results: Dict[str, Any],
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Investigate retrieved evidence to find patterns and root causes.

        Args:
            query: Original query that triggered investigation.
            retrieval_results: Results from retrieval agent (with chunks).
            file_path: Optional path to original log file for additional analysis.

        Returns:
            Dictionary with investigation findings:
            {
                "query": str,
                "findings": List[Dict],
                "patterns": Dict,
                "sequences": List[Dict],
                "root_causes": List[str],
                "timeline": List[Dict],
                "summary": str
            }
        """
        chunks = retrieval_results.get("chunks", [])
        findings: List[Dict[str, Any]] = []
        patterns: Dict[str, Any] = defaultdict(int)
        sequences: List[Dict[str, Any]] = []
        root_causes: List[str] = []
        timeline: List[Dict[str, Any]] = []

        # Analyze each chunk
        for chunk in chunks:
            content = chunk.get("content", "")
            metadata = chunk.get("metadata", {})
            chunk_id = chunk.get("chunk_id", "")

            # Extract patterns
            self._extract_patterns(content, patterns)

            # Extract timeline events
            event = self._extract_timeline_event(content, metadata, chunk_id)
            if event:
                timeline.append(event)

            # Find error sequences
            if self._is_error_chunk(content):
                sequence = self._extract_error_sequence(chunk, chunks)
                if sequence:
                    sequences.append(sequence)

        # Analyze sequences for root causes
        root_causes = self._identify_root_causes(sequences, patterns)

        # Build findings
        for sequence in sequences[:5]:  # Top 5 sequences
            findings.append({
                "type": "error_sequence",
                "description": sequence.get("description", ""),
                "error_codes": sequence.get("error_codes", []),
                "services": sequence.get("services", []),
                "timeline": sequence.get("timeline", []),
                "severity": sequence.get("severity", "medium"),
            })

        # Add pattern findings
        top_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]
        for pattern, count in top_patterns:
            findings.append({
                "type": "pattern",
                "pattern": pattern,
                "frequency": count,
                "description": f"Pattern '{pattern}' appears {count} times",
            })

        # Build summary
        summary = self._build_investigation_summary(
            query, findings, root_causes, len(chunks)
        )

        return {
            "query": query,
            "findings": findings,
            "patterns": dict(patterns),
            "sequences": sequences[:10],  # Top 10 sequences
            "root_causes": root_causes,
            "timeline": sorted(timeline, key=lambda x: x.get("timestamp", "")),
            "summary": summary,
            "metadata": {
                "chunks_analyzed": len(chunks),
                "findings_count": len(findings),
                "sequences_count": len(sequences),
            },
        }

    def _extract_patterns(self, content: str, patterns: Dict[str, int]) -> None:
        """Extract patterns from content."""
        # Error codes
        error_codes = re.findall(r'\b[A-Z]{2,6}\d{3,4}[EI]?\b', content)
        for code in error_codes:
            patterns[f"error_code:{code}"] += 1

        # Timeout patterns
        if re.search(r'\btimeout\b', content, re.IGNORECASE):
            patterns["pattern:timeout"] += 1

        # Connection failures
        if re.search(r'\b(connection|connect|failed|failure)\b', content, re.IGNORECASE):
            patterns["pattern:connection_failure"] += 1

        # Retry patterns
        if re.search(r'\b(retry|retrying|attempt)\b', content, re.IGNORECASE):
            patterns["pattern:retry"] += 1

    def _extract_timeline_event(
        self, content: str, metadata: Dict, chunk_id: str
    ) -> Optional[Dict[str, Any]]:
        """Extract timeline event from chunk."""
        # Try to extract timestamp
        timestamp = None
        if metadata.get("timestamp"):
            try:
                timestamp = date_parser.parse(str(metadata["timestamp"]), fuzzy=True)
            except Exception:
                pass

        # Extract log level
        log_level = metadata.get("log_level", "")
        if not log_level:
            if re.search(r'\b(ERROR|FATAL|CRITICAL)\b', content):
                log_level = "ERROR"
            elif re.search(r'\b(WARN|WARNING)\b', content):
                log_level = "WARN"

        # Extract service
        service = metadata.get("service", "")
        if not service:
            service_match = re.search(r'\[([A-Za-z0-9_-]+)\]', content)
            if service_match:
                service = service_match.group(1)

        if timestamp or log_level:
            return {
                "chunk_id": chunk_id,
                "timestamp": timestamp.isoformat() if timestamp else None,
                "log_level": log_level,
                "service": service,
                "content_preview": content[:200],
            }

        return None

    def _is_error_chunk(self, content: str) -> bool:
        """Check if chunk contains errors."""
        return bool(
            re.search(r'\b(ERROR|FATAL|CRITICAL|Exception|Failed|Failure)\b', content, re.IGNORECASE)
        )

    def _extract_error_sequence(
        self, error_chunk: Dict[str, Any], all_chunks: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Extract error sequence from chunk."""
        content = error_chunk.get("content", "")
        metadata = error_chunk.get("metadata", {})

        # Extract error codes
        error_codes = re.findall(r'\b[A-Z]{2,6}\d{3,4}[EI]?\b', content)

        # Extract service
        service = metadata.get("service", "")
        if not service:
            service_match = re.search(r'\[([A-Za-z0-9_-]+)\]', content)
            service = service_match.group(1) if service_match else "Unknown"

        # Determine severity
        severity = "medium"
        if re.search(r'\b(FATAL|CRITICAL)\b', content, re.IGNORECASE):
            severity = "high"
        elif re.search(r'\b(WARN|WARNING)\b', content, re.IGNORECASE):
            severity = "low"

        # Build description
        lines = content.split("\n")[:3]
        description = " | ".join(line.strip() for line in lines if line.strip())

        return {
            "chunk_id": error_chunk.get("chunk_id", ""),
            "description": description[:500],
            "error_codes": list(set(error_codes)),
            "services": [service] if service else [],
            "severity": severity,
            "timeline": [{
                "timestamp": metadata.get("timestamp", ""),
                "event": description[:200],
            }],
        }

    def _identify_root_causes(
        self, sequences: List[Dict[str, Any]], patterns: Dict[str, int]
    ) -> List[str]:
        """Identify potential root causes from sequences and patterns."""
        root_causes: List[str] = []

        # Check for timeout patterns
        if patterns.get("pattern:timeout", 0) > 0:
            root_causes.append("Timeout issues detected - may indicate network or resource constraints")

        # Check for connection failures
        if patterns.get("pattern:connection_failure", 0) > 0:
            root_causes.append("Connection failures detected - may indicate database or service connectivity issues")

        # Check for retry patterns
        if patterns.get("pattern:retry", 0) > 0:
            root_causes.append("Retry patterns detected - system attempting to recover from transient failures")

        # Check for specific error codes
        error_code_patterns = {
            k: v for k, v in patterns.items() if k.startswith("error_code:")
        }
        if error_code_patterns:
            top_error = max(error_code_patterns.items(), key=lambda x: x[1])
            root_causes.append(f"Frequent error code: {top_error[0].split(':')[1]} (appears {top_error[1]} times)")

        # Analyze sequences
        if sequences:
            high_severity = [s for s in sequences if s.get("severity") == "high"]
            if high_severity:
                root_causes.append(f"{len(high_severity)} high-severity error sequences detected")

        return root_causes[:5]  # Top 5 root causes

    def _build_investigation_summary(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        root_causes: List[str],
        chunks_analyzed: int,
    ) -> str:
        """Build investigation summary text."""
        summary_parts = [
            f"Investigation of '{query}' analyzed {chunks_analyzed} log chunks.",
        ]

        if root_causes:
            summary_parts.append(f"Identified {len(root_causes)} potential root causes:")
            for i, cause in enumerate(root_causes, 1):
                summary_parts.append(f"  {i}. {cause}")

        if findings:
            error_sequences = [f for f in findings if f.get("type") == "error_sequence"]
            if error_sequences:
                summary_parts.append(f"Found {len(error_sequences)} error sequences.")

        return "\n".join(summary_parts)

    def save_findings(
        self, findings: Dict[str, Any], output_path: str
    ) -> str:
        """
        Save investigation findings to JSON file.

        Args:
            findings: Investigation findings dictionary.
            output_path: Path to save findings.json.

        Returns:
            Path to saved file.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(findings, f, indent=2, default=str)

        return output_path
