"""Deterministic RCA output analysis agent (read-only)."""

from __future__ import annotations

from agents.agent_models import AgentFinding, AgentInvestigationContext
from agents.base_agent import BaseAgent


class RCAAgent(BaseAgent):
    name = "rca"

    def investigate(self, context: AgentInvestigationContext) -> AgentFinding:
        observations: list[str] = []
        suspicious: list[str] = []
        correlations: list[str] = []

        record = context.store_record or {}
        bundle = record.get("relationship_ready_bundle") or {}
        target = str(bundle.get("rca_target_file") or "").strip()
        assessments = record.get("confidence_assessments") or []
        run_status = str(record.get("run_status") or "").strip().lower()
        feedback = context.feedback

        if run_status == "completed":
            observations.append("Deterministic RCA run completed for this investigation.")
        else:
            observations.append(f"RCA run status: {run_status or 'unknown'}.")

        if target:
            observations.append(f"Top ranked RCA candidate: {target}")
            correlations.append(f"rca_candidate:{target}")
        else:
            observations.append("No RCA target file recorded in investigation store.")

        top_confidence = 0.0
        top_level = "unknown"
        if isinstance(assessments, list) and assessments:
            top = assessments[0] if isinstance(assessments[0], dict) else {}
            try:
                top_confidence = float(top.get("confidence") or 0.0)
            except (TypeError, ValueError):
                top_confidence = 0.0
            top_level = str(top.get("confidence_level") or "unknown")
            observations.append(f"Confidence engine: {top_confidence:.2f} ({top_level}).")
            for factor in top.get("supporting_factors") or []:
                correlations.append(f"support:{factor}")
            for factor in top.get("contradicting_factors") or []:
                suspicious.append(str(factor))

            if len(assessments) > 1:
                observations.append(f"{len(assessments)} ranked candidate(s) in RCA output.")
        else:
            observations.append("No confidence assessments stored for this investigation.")

        if feedback:
            observations.append(f"Engineer feedback recorded ({len(feedback)} item(s)).")
            latest = feedback[0]
            observations.append(f"Latest feedback: {latest.feedback_type} on {latest.candidate_id}")
            correlations.append(f"feedback:{latest.feedback_type.lower()}")

        confidence = top_confidence if top_confidence > 0 else (0.5 if target else 0.1)
        summary = (
            f"RCA analysis identified '{target or 'no candidate'}' with confidence {top_confidence:.2f}."
            if target
            else "RCA output available but no leading candidate was persisted."
        )
        return AgentFinding(
            agent_name=self.name,
            summary=summary,
            key_observations=observations,
            suspicious_items=suspicious,
            correlations=correlations,
            confidence=round(min(0.99, confidence), 4),
            evidence={
                "rca_target_file": target,
                "confidence_level": top_level,
                "feedback_count": len(feedback),
            },
        )
