"""Unit tests for RCA signal coverage audit script."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "audit_rca_signal_coverage.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("audit_rca_signal_coverage", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_audit_covers_all_signals() -> None:
    mod = _load_module()
    report = mod.run_audit()
    ids = {signal.signal_id for signal in report.signals}
    assert ids == set(mod.SIGNAL_IDS)


def test_ownership_is_missing() -> None:
    mod = _load_module()
    ownership = next(signal for signal in mod.run_audit().signals if signal.signal_id == "ownership")
    assert ownership.used_in_ranking == "no"
    assert ownership.used_in_confidence == "no"
    assert ownership.used_in_report == "no"


def test_stack_trace_and_deployment_ranked() -> None:
    mod = _load_module()
    by_id = {signal.signal_id: signal for signal in mod.run_audit().signals}
    assert by_id["stack_trace"].used_in_ranking == "yes"
    assert by_id["deployment"].used_in_ranking == "yes"
    assert by_id["coverage"].used_in_ranking == "no"


def test_write_reports_creates_markdown(tmp_path) -> None:
    mod = _load_module()
    report = mod.run_audit()
    json_path, md_path = mod.write_reports(report, tmp_path)
    assert md_path.name == "rca_audit_report.md"
    text = md_path.read_text(encoding="utf-8")
    assert "## Signal Coverage Matrix" in text
    assert "Stack Trace Signal" in text
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == len(mod.SIGNAL_IDS)
