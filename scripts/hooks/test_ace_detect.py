"""Tests for the ACE PostToolUse hook."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HOOK_SCRIPT = Path(__file__).parent / "ace-detect.py"


def _run_hook(payload: dict, cwd: str | None = None) -> tuple[int, dict | None]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=cwd,
    )
    stdout_json = None
    if proc.stdout.strip():
        stdout_json = json.loads(proc.stdout)
    return proc.returncode, stdout_json


def test_record_operation_writes_reflect_log_for_snake_case_payload(tmp_path: Path) -> None:
    payload = {
        "tool_name": "mcp__agent-handoff-mcp__review_findings",
        "tool_input": {
            "review": {
                "operation": "record",
                "finding_id": "M-1",
                "description": "This violates [sr-001] because the hook is missing.",
            }
        },
    }

    exit_code, output = _run_hook(payload, cwd=str(tmp_path))

    assert exit_code == 0
    assert output == {"result": "continue"}
    reflect_log = tmp_path / ".task-state" / "ace_reflect_log.jsonl"
    assert reflect_log.exists()
    record = json.loads(reflect_log.read_text(encoding="utf-8").strip())
    assert record["finding_id"] == "M-1"
    assert record["rule_id"] == "sr-001"
    assert record["contradicts"] is True


def test_record_operation_writes_reflect_log_for_camel_case_payload(tmp_path: Path) -> None:
    payload = {
        "toolName": "mcp__agent-handoff-mcp__review_findings",
        "toolInput": {
            "review": {
                "operation": "record",
                "finding_id": "M-1",
                "description": "This violates [rg-010] because the hook was bypassed.",
            }
        },
    }

    exit_code, output = _run_hook(payload, cwd=str(tmp_path))

    assert exit_code == 0
    assert output == {"result": "continue"}
    reflect_log = tmp_path / ".task-state" / "ace_reflect_log.jsonl"
    assert reflect_log.exists()
    record = json.loads(reflect_log.read_text(encoding="utf-8").strip())
    assert record["finding_id"] == "M-1"
    assert record["rule_id"] == "rg-010"
    assert record["contradicts"] is True