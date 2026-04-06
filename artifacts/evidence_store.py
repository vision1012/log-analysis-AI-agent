"""File-backed evidence bundles for deterministic RCA (create + load by ref)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional, Protocol


class EvidenceStore(Protocol):
    """Bundle storage: ``evidence_ref`` from :meth:`create_bundle` keys :meth:`get_bundle`."""

    def get_bundle(self, evidence_ref: str) -> Optional[dict[str, Any]]: ...

    def create_bundle(self, payload: dict[str, Any]) -> str: ...


class LocalFileEvidenceStore:
    """Stores each bundle as ``<root>/<uuid>.json``."""

    def __init__(self, base_dir: str | Path) -> None:
        self._root = Path(base_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def get_bundle(self, evidence_ref: str) -> Optional[dict[str, Any]]:
        if not evidence_ref or not evidence_ref.strip():
            return None
        path = self._root / f"{evidence_ref.strip()}.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def create_bundle(self, payload: dict[str, Any]) -> str:
        bundle_id = str(uuid.uuid4())
        out = dict(payload)
        out.setdefault("bundle_id", bundle_id)
        path = self._root / f"{bundle_id}.json"
        path.write_text(json.dumps(out, default=str), encoding="utf-8")
        return bundle_id
