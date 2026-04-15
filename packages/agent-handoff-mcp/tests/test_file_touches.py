from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_env(tmp_path: Path) -> dict:
    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
    mcp_server.configure_runtime(runtime)
    handoff_core.set_handoff_state(
        task_ref="file-touch-task",
        objective="File touch query coverage",
        status="in_progress",
    )
    return {"state_dir": state_dir, "task_ref": "file-touch-task"}


def _parse(payload: str | dict) -> dict:
    raw = json.loads(payload) if isinstance(payload, str) else payload
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        return {**raw, **raw.get("data", {})}
    return raw


def test_record_file_touch_and_get_touched_files_roundtrip(isolated_env: dict) -> None:
    recorded = _parse(
        handoff_core.record_file_touch(
            file_path="packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py",
            change_kind="edit",
            session="s1",
        )
    )

    assert recorded["ok"] is True
    touch = recorded["touch"]
    assert touch["task_ref"] == "file-touch-task"
    assert touch["file_path"] == "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py"
    assert touch["change_kind"] == "edit"
    assert touch["session"] == "s1"
    assert recorded["mutation"]["entity"] == "touched_file"
    assert recorded["mutation"]["operation"] == "insert"

    listed = _parse(handoff_core.get_touched_files())

    assert listed["ok"] is True
    assert listed["task_ref"] == "file-touch-task"
    assert listed["returned"] == 1
    assert listed["touches"][0]["file_path"] == "packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py"
    assert listed["touches"][0]["change_kind"] == "edit"


def test_get_touched_files_defaults_to_active_task_scope_and_limit(isolated_env: dict) -> None:
    handoff_core.record_file_touch(
        file_path="packages/agent-handoff-mcp/tests/test_file_touches.py",
        change_kind="add",
        session="s1",
        task_ref="file-touch-task",
    )
    handoff_core.record_file_touch(
        file_path="packages/agent-handoff-mcp/tests/test_http.py",
        change_kind="edit",
        session="s1",
        task_ref="other-task",
    )
    handoff_core.record_file_touch(
        file_path="packages/agent-handoff-mcp/tests/test_stdio.py",
        change_kind="edit",
        session="s1",
        task_ref="file-touch-task",
    )

    listed = _parse(handoff_core.get_touched_files(limit=1))

    assert listed["ok"] is True
    assert listed["task_ref"] == "file-touch-task"
    assert listed["total_matching"] == 2
    assert listed["returned"] == 1
    assert listed["has_more"] is True
    assert [row["file_path"] for row in listed["touches"]] == [
        "packages/agent-handoff-mcp/tests/test_stdio.py",
    ]


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "/Users/daniel/some/file.py",
        "packages/../../../etc/passwd",
        "foo/bar/../../baz/../../../etc/shadow",
    ],
)
def test_record_file_touch_rejects_non_relative_paths(isolated_env: dict, bad_path: str) -> None:
    result = _parse(
        handoff_core.record_file_touch(
            file_path=bad_path,
            change_kind="edit",
            session="s1",
        )
    )
    assert result["ok"] is False
    assert "monorepo-relative" in result["error"]


def test_record_file_touch_accepts_relative_paths(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_file_touch(
            file_path="packages/agent-handoff-mcp/src/some_file.py",
            change_kind="add",
            session="s1",
        )
    )
    assert result["ok"] is True
    assert result["touch"]["file_path"] == "packages/agent-handoff-mcp/src/some_file.py"