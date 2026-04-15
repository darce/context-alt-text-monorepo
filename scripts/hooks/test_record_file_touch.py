"""Tests for the record-file-touch PostToolUse hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).parent / "record-file-touch.py"


def _run_hook(payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
        cwd=cwd,
    )


def test_edit_tool_exits_zero() -> None:
    """Hook exits 0 for Edit tool calls (best-effort, never blocks)."""
    result = _run_hook({
        "tool_name": "Edit",
        "tool_input": {"file_path": "/tmp/test_file.py", "old_string": "a", "new_string": "b"},
        "tool_response": {"success": True},
    })
    assert result.returncode == 0


def test_write_tool_exits_zero() -> None:
    """Hook exits 0 for Write tool calls."""
    result = _run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/test_file.py", "content": "hello"},
        "tool_response": {"success": True},
    })
    assert result.returncode == 0


def test_non_edit_write_tool_exits_zero() -> None:
    """Hook exits 0 immediately for non-Edit/Write tools."""
    result = _run_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {"stdout": "file.py"},
    })
    assert result.returncode == 0


def test_malformed_json_exits_zero() -> None:
    """Hook exits 0 on malformed input (best-effort)."""
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0


def test_empty_file_path_exits_zero() -> None:
    """Hook exits 0 when file_path is empty."""
    result = _run_hook({
        "tool_name": "Edit",
        "tool_input": {"file_path": "", "old_string": "a", "new_string": "b"},
    })
    assert result.returncode == 0


def test_determine_change_kind_edit_tool() -> None:
    """Edit tool always produces change_kind='edit'."""
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("record_file_touch_hook", str(HOOK_SCRIPT))
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._determine_change_kind("Edit", "/tmp/any_file.py") == "edit"


def test_determine_change_kind_write_untracked(tmp_path: Path) -> None:
    """Write tool on an untracked file produces change_kind='add'."""
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("record_file_touch_hook", str(HOOK_SCRIPT))
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    untracked = tmp_path / "new_file.py"
    untracked.write_text("hello")
    assert mod._determine_change_kind("Write", str(untracked)) == "add"
