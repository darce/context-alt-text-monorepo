from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "regenerate-task-views.sh"


def _write_fake_cli(tmp_path: Path) -> Path:
    fake_cli = tmp_path / "agent-handoff-mcp"
    fake_cli.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"$@\" >> \"$TMP_HOOK_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IEXEC)
    return fake_cli


def _run_hook(tmp_path: Path, payload: dict) -> tuple[int, str]:
    _write_fake_cli(tmp_path)
    log_path = tmp_path / "calls.log"
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env.get('PATH', '')}"
    env["TMP_HOOK_LOG"] = str(log_path)
    proc = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=5,
    )
    calls = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    return proc.returncode, calls


def test_review_findings_list_string_payload_is_skipped(tmp_path: Path) -> None:
    code, calls = _run_hook(
        tmp_path,
        {
            "tool_name": "mcp__altcontext_mcp__review_findings",
            "tool_input": {"review": '{"operation":"list"}'},
        },
    )
    assert code == 0
    assert calls == ""


def test_review_findings_record_string_payload_triggers_refresh(tmp_path: Path) -> None:
    code, calls = _run_hook(
        tmp_path,
        {
            "tool_name": "mcp__altcontext_mcp__review_findings",
            "tool_input": {"review": '{"operation":"record"}'},
        },
    )
    assert code == 0
    assert "--workspace-root" in calls
    assert "write-dashboard" in calls
