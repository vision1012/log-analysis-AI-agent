"""Lightweight persistence for JIRA-first RCA investigation traces."""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


class InvestigationStore(ABC):
    """Interface for storing investigation trace records."""

    @abstractmethod
    def create_record(self, payload: dict[str, Any]) -> str:
        """Persist one investigation record and return investigation_id."""

    @abstractmethod
    def get_record(self, investigation_id: str) -> Optional[dict[str, Any]]:
        """Load a persisted investigation record by id."""

    @abstractmethod
    def cleanup_older_than(self, days: int) -> int:
        """Delete records older than N days. Returns deleted count."""


class LocalFileInvestigationStore(InvestigationStore):
    """JSON file-backed minimal investigation persistence."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def create_record(self, payload: dict[str, Any]) -> str:
        investigation_id = str(payload.get("investigation_id") or uuid.uuid4())
        out = dict(payload)
        out["investigation_id"] = investigation_id
        out.setdefault("schema_version", "1.0.0")
        out.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        path = self._base / f"{investigation_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, default=str)
        return investigation_id

    def get_record(self, investigation_id: str) -> Optional[dict[str, Any]]:
        path = self._base / f"{investigation_id}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def cleanup_older_than(self, days: int) -> int:
        if days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0
        for path in self._base.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                created_raw = str(data.get("created_at") or "")
                created_at = _parse_iso(created_raw)
                if created_at and created_at < cutoff:
                    path.unlink(missing_ok=True)
                    deleted += 1
            except Exception:
                # Keep unreadable/corrupt records for manual inspection.
                continue
        return deleted


def _parse_iso(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None
