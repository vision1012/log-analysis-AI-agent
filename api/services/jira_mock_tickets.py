"""Deterministic mock JIRA tickets for RCA demo / frontend fetch without live JIRA."""

from __future__ import annotations

from schemas.jira import MockJiraTicketResponse

_MOCK_TICKETS: dict[str, MockJiraTicketResponse] = {
    "LAAA-78": MockJiraTicketResponse(
        ticket_key="LAAA-78",
        title="Users unable to complete MFA authentication",
        description="OTP validation timeout during MFA verification.",
        labels=["sev1", "auth", "mfa"],
        status="open",
        priority="high",
    ),
    "LAAA-79": MockJiraTicketResponse(
        ticket_key="LAAA-79",
        title="Invalid token parsing during MFA authentication",
        description="Malformed OTP token causing authentication failures.",
        labels=["sev1", "auth", "token"],
        status="open",
        priority="high",
    ),
}


def normalize_ticket_key(ticket_key: str) -> str:
    return (ticket_key or "").strip().upper()


def get_mock_jira_ticket(ticket_key: str) -> MockJiraTicketResponse | None:
    """Return a demo ticket by key, or None if not in the mock catalog."""
    return _MOCK_TICKETS.get(normalize_ticket_key(ticket_key))
