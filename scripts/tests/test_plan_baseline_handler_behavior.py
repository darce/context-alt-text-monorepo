from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDLER = REPO_ROOT / "scripts/workstate/lifecycle/handlers/plan_baseline.py"
HANDLER_ID = "scripts/workstate/lifecycle/handlers/plan_baseline.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HANDLER), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _payload(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.stdout, completed.stderr
    payload = json.loads(completed.stdout.splitlines()[0])
    assert isinstance(payload, dict)
    return payload


def test_missing_plan_exits_2_with_missing_plan_status() -> None:
    completed = _run("--task", "ISSUEDAG-1")
    payload = _payload(completed)
    assert completed.returncode == 2
    assert payload["status"] == "missing_plan"
    assert payload["handler"] == HANDLER_ID
    assert payload["task"] == "ISSUEDAG-1"
    assert "PLAN=" in completed.stderr


def test_blank_plan_is_missing_plan() -> None:
    completed = _run("--task", "ISSUEDAG-1", "--plan", "  ")
    payload = _payload(completed)
    assert completed.returncode == 2
    assert payload["status"] == "missing_plan"


def test_blank_task_exits_2_with_missing_task_status(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    completed = _run("--task", "   ", "--plan", str(plan))
    payload = _payload(completed)
    assert completed.returncode == 2
    assert payload["status"] == "missing_task"
    assert "TASK=" in completed.stderr


def test_missing_file_exits_1(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-plan.md"
    completed = _run("--task", "ISSUEDAG-1", "--plan", str(missing))
    payload = _payload(completed)
    assert completed.returncode == 1
    assert payload["status"] == "missing_file"
    assert "plan file not found" in completed.stderr


def test_directory_plan_is_missing_file(tmp_path: Path) -> None:
    plan_dir = tmp_path / "plan-dir"
    plan_dir.mkdir()
    completed = _run("--task", "ISSUEDAG-1", "--plan", str(plan_dir))
    payload = _payload(completed)
    assert completed.returncode == 1
    assert payload["status"] == "missing_file"


def test_validates_existing_plan_file(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# plan\n", encoding="utf-8")
    completed = _run("--task", "ISSUEDAG-1", "--plan", str(plan))
    payload = _payload(completed)
    assert completed.returncode == 0, completed.stderr
    assert payload["status"] == "validated_only"
    assert payload["handler"] == HANDLER_ID
    assert payload["task"] == "ISSUEDAG-1"
    assert payload["plan"] == str(plan.resolve())
    assert "nothing was landed" in completed.stderr
    assert "accepted" not in completed.stdout


def test_validates_empty_plan_file(tmp_path: Path) -> None:
    plan = tmp_path / "empty.md"
    plan.write_text("", encoding="utf-8")
    completed = _run("--task", "ISSUEDAG-1", "--plan", str(plan))
    payload = _payload(completed)
    assert completed.returncode == 0, completed.stderr
    assert payload["status"] == "validated_only"
    assert payload["plan"] == str(plan.resolve())
    assert "nothing was landed" in completed.stderr
    assert "accepted" not in completed.stdout


def test_docstring_describes_overlay_absent_fallback() -> None:
    module_docstring = ast.get_docstring(ast.parse(HANDLER.read_text(encoding="utf-8")))
    assert module_docstring is not None
    assert "Makefile.d/plans.mk" in module_docstring
    assert "fallback" in module_docstring
