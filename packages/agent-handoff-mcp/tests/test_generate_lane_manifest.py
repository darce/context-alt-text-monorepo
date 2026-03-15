from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "generate_lane_manifest.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_lane_manifest", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generate_lane_manifest module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_manifest_is_generic_to_any_task() -> None:
    mod = _load_module()
    manifest = mod.build_manifest(
        task_ref="example-task",
        lane_ids=["backend", "frontend"],
        task_plan="docs/tasks/example-task-plan.md",
    )

    assert manifest["task_ref"] == "example-task"
    assert manifest["merge_order"] == ["backend", "frontend"]
    assert manifest["lanes"]["backend"]["branch"] == "codex/example-task-backend"
    assert manifest["lanes"]["frontend"]["worktree_path"] == "{orchestrator_root}-example-task-frontend"
    assert "docs/tasks/example-task-plan.md" in manifest["lanes"]["backend"]["required_docs"]
    assert manifest["downstream"]["backend"] == ["frontend"]
    assert manifest["downstream"]["frontend"] == []


def test_build_manifest_defaults_route_hints_and_empty_scope() -> None:
    mod = _load_module()
    manifest = mod.build_manifest(
        task_ref="t",
        lane_ids=["wp-proxy"],
    )

    lane = manifest["lanes"]["wp-proxy"]
    assert lane["owned_paths"] == []
    assert lane["test_commands"] == []
    assert lane["commit_paths"] == []
    assert "wp-proxy" in lane["route_hints"]
    assert "wp proxy" in lane["route_hints"]


def test_humanize_lane_handles_short_and_empty_parts() -> None:
    mod = _load_module()
    assert mod._humanize_lane("wp-proxy") == "WP Proxy"
    assert mod._humanize_lane("backend-domain") == "Backend Domain"
    assert mod._humanize_lane("") == ""


def test_route_hints_deduplicate_variants() -> None:
    mod = _load_module()
    assert mod._route_hints("backend", "Backend") == ["backend", "Backend"]


def test_main_stdout_renders_json(tmp_path: Path, capsys) -> None:
    mod = _load_module()
    argv = [
        str(SCRIPT_PATH),
        "--task-ref", "demo-task",
        "--lane", "backend",
        "--stdout",
    ]
    with mock.patch.object(sys, "argv", argv):
        assert mod.main() == 0

    rendered = json.loads(capsys.readouterr().out)
    assert rendered["task_ref"] == "demo-task"
    assert rendered["lanes"]["backend"]["branch"] == "codex/demo-task-backend"


def test_main_force_overwrites_existing_file(tmp_path: Path) -> None:
    mod = _load_module()
    output = tmp_path / "manifest.json"
    output.write_text('{"stale": true}\n')
    argv = [
        str(SCRIPT_PATH),
        "--task-ref", "demo-task",
        "--lane", "backend",
        "--output", str(output),
        "--force",
    ]
    with mock.patch.object(sys, "argv", argv):
        assert mod.main() == 0

    rendered = json.loads(output.read_text())
    assert rendered["task_ref"] == "demo-task"
    assert "backend" in rendered["lanes"]
