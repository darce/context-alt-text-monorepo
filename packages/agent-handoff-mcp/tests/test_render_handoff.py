"""Tests for the ``render_handoff`` compound MCP tool (E17-7 Slice 4A).

Slice 4A compresses the two single-purpose rendering tools (``generate_current_task_md``
and ``generate_dashboard_md``) into one compound tool ``render_handoff(kind=...)``.

Contract:

- ``render_handoff(kind="current_task", task_ref=..., write_file=...)`` produces the
  same envelope shape and side effects as the legacy ``generate_current_task_md`` call,
  writing ``CURRENT_TASK.json`` at the workspace root.
- ``render_handoff(kind="dashboard", write_file=...)`` produces the same envelope shape
  and side effects as the legacy ``generate_dashboard_md`` call, writing
  ``DASHBOARD.txt`` at the workspace root with no ``DASHBOARD.md`` artifact.
- The Python-level aliases ``generate_current_task_md`` and ``generate_dashboard_md``
  continue to resolve for backward compatibility with existing callers.
- The MCP tool registry exposes ``render_handoff`` (compound) and does not re-register
  the retired single-purpose names.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_handoff(tmp_path: Path):
    state_dir = tmp_path / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    current_task_path = tmp_path / "CURRENT_TASK.json"
    dashboard_path = tmp_path / "DASHBOARD.txt"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
        current_task_path=current_task_path,
        dashboard_path=dashboard_path,
    )
    mcp_server.configure_runtime(runtime)
    return {
        "workspace": tmp_path,
        "current_task_path": current_task_path,
        "dashboard_path": dashboard_path,
    }


def _parse(payload: str | dict) -> dict:
    raw = payload if isinstance(payload, dict) else json.loads(payload)
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        data = raw.get("data", {})
        scope = raw.get("scope", {})
        flat = {**raw, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return raw


def _seed_task(task_ref: str) -> None:
    _parse(
        mcp_server.set_handoff_state(
            task_ref=task_ref,
            objective="Exercise render_handoff compound tool",
            status="in_progress",
        )
    )


def test_render_handoff_current_task_matches_legacy_envelope(isolated_handoff: dict) -> None:
    _seed_task("render-handoff-current")

    compound = _parse(
        mcp_server.render_handoff(kind="current_task", task_ref="render-handoff-current", write_file=False)
    )

    assert compound["ok"] is True
    assert compound["tool"] == "render_handoff"
    assert compound["task_ref"] == "render-handoff-current"
    assert compound["path"].endswith("CURRENT_TASK.json")
    assert compound["written"] is False
    assert compound["current_task_json"] is not None
    assert json.loads(compound["current_task_json"])["task_ref"] == "render-handoff-current"


def test_render_handoff_current_task_writes_file(isolated_handoff: dict) -> None:
    _seed_task("render-handoff-current-write")

    compound = _parse(mcp_server.render_handoff(kind="current_task", task_ref="render-handoff-current-write"))

    assert compound["written"] is True
    current_task_path = isolated_handoff["current_task_path"]
    assert current_task_path.exists()
    body = json.loads(current_task_path.read_text())
    assert body["task_ref"] == "render-handoff-current-write"


def test_render_handoff_dashboard_writes_txt(isolated_handoff: dict) -> None:
    _seed_task("render-handoff-dashboard")

    compound = _parse(mcp_server.render_handoff(kind="dashboard"))

    assert compound["ok"] is True
    assert compound["tool"] == "render_handoff"
    dashboard_path = isolated_handoff["dashboard_path"]
    assert dashboard_path.exists(), "render_handoff(kind='dashboard') must write DASHBOARD.txt"
    # No .md sibling should be produced.
    assert not (isolated_handoff["workspace"] / "DASHBOARD.md").exists()


def test_render_handoff_dashboard_respects_no_write(isolated_handoff: dict) -> None:
    _seed_task("render-handoff-dashboard-nowrite")

    compound = _parse(mcp_server.render_handoff(kind="dashboard", write_file=False))

    assert compound["ok"] is True
    assert not isolated_handoff["dashboard_path"].exists()


def test_render_handoff_rejects_unknown_kind(isolated_handoff: dict) -> None:
    with pytest.raises(Exception):
        mcp_server.render_handoff(kind="bogus")  # type: ignore[arg-type]


def test_python_aliases_still_resolve(isolated_handoff: dict) -> None:
    """Existing callers that import the old names must keep working."""
    _seed_task("alias-task")

    legacy_current = _parse(mcp_server.generate_current_task_md(task_ref="alias-task", write_file=False))
    assert legacy_current["ok"] is True
    assert legacy_current["task_ref"] == "alias-task"

    legacy_dashboard = _parse(mcp_server.generate_dashboard_md(write_file=False))
    assert legacy_dashboard["ok"] is True


def test_package_exports_include_render_handoff() -> None:
    import agent_handoff_mcp as pkg

    assert hasattr(pkg, "render_handoff"), "render_handoff must be exported from the package root"
    assert "render_handoff" in pkg.__all__


def test_tool_registry_exposes_render_handoff_and_retires_old_names() -> None:
    registry = mcp_server._build_tool_registry()  # type: ignore[attr-defined]
    names = {entry.name for entry in registry}

    assert "render_handoff" in names
    assert "generate_current_task_md" not in names
    assert "generate_dashboard_md" not in names
    assert "generate_md" not in names
