from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "lane_manifest.py"


def _load_lane_manifest_module():
    spec = importlib.util.spec_from_file_location("lane_manifest", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_manifest module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def manifest_module(tmp_path: Path):
    module = _load_lane_manifest_module()
    manifest_dir = tmp_path / "lane-orchestration"
    manifest_dir.mkdir()
    manifest = {
        "task_ref": "demo-task",
        "task_plan_path": "docs/tasks/demo-task-plan.md",
        "default_done_definition": "done",
        "merge_order": ["backend", "frontend"],
        "heading_to_lane": {
            "Phase 1: Backend": "backend",
            "Phase 2: Frontend": "frontend",
        },
        "plan_routing_hints": [
            {
                "heading": "Phase 3: Integration",
                "text_prefix": "Backend integration test:",
                "lane": "backend",
            }
        ],
        "routing": [],
        "lanes": {
            "backend": {
                "branch": "codex/demo-backend",
                "worktree_path": "{orchestrator_root}-demo-backend",
                "title": "Backend",
                "objective": "Backend work",
                "owned_paths": ["apps/backend/**", "docs/demo.md"],
                "required_docs": ["docs/agentic/instructions.md"],
                "test_commands": ["pytest apps/backend/tests -q"],
                "non_goals": [],
                "route_hints": ["backend lane"],
                "guidance_fallbacks": [
                    {
                        "match_any": ["remaining backend slice"],
                        "subject": "backend next slice",
                        "message": "Finish the backend slice.",
                    }
                ],
                "tooling_paths": ["apps/backend/Makefile"],
            },
            "frontend": {
                "branch": "codex/demo-frontend",
                "worktree_path": "{orchestrator_root}-demo-frontend",
                "title": "Frontend",
                "objective": "Frontend work",
                "owned_paths": ["apps/frontend/**"],
                "required_docs": ["docs/agentic/instructions.md"],
                "test_commands": ["npm test"],
                "non_goals": [],
                "commit_paths": ["apps/frontend"],
                "route_hints": ["frontend lane"],
                "guidance_fallbacks": [],
                "tooling_paths": [],
            },
        },
        "downstream": {"backend": ["frontend"], "frontend": []},
    }
    (manifest_dir / "demo-task.json").write_text(json.dumps(manifest))
    original_dir = module.MANIFEST_DIR
    module.MANIFEST_DIR = manifest_dir
    try:
        yield module
    finally:
        module.MANIFEST_DIR = original_dir


def test_list_task_refs_reads_fixture_manifest(manifest_module) -> None:
    assert manifest_module.list_task_refs() == ["demo-task"]


def test_infer_lane_from_branch_uses_fixture_manifest(manifest_module) -> None:
    lane_id = manifest_module.infer_lane_from_branch("codex/demo-frontend", "demo-task")
    assert lane_id == "frontend"


def test_infer_task_from_branch_or_worktree_uses_branch_match(manifest_module) -> None:
    task_ref = manifest_module.infer_task_from_branch_or_worktree("codex/demo-frontend")
    assert task_ref == "demo-task"


def test_infer_task_from_branch_or_worktree_uses_worktree_match(manifest_module) -> None:
    task_ref = manifest_module.infer_task_from_branch_or_worktree(
        "feature/unknown",
        worktree_path="/tmp/context-alt-text-monorepo-demo-backend",
        orchestrator_root="/tmp/context-alt-text-monorepo",
    )
    assert task_ref == "demo-task"


def test_get_lane_config_expands_worktree_template_and_derives_commit_paths(manifest_module) -> None:
    lane = manifest_module.get_lane_config(
        "demo-task",
        "backend",
        orchestrator_root="/tmp/context-alt-text-monorepo",
    )
    assert lane is not None
    assert lane["worktree_path"] == "/tmp/context-alt-text-monorepo-demo-backend"
    assert lane["commit_paths"] == ["apps/backend", "docs/demo.md"]


def test_route_patterns_derives_from_owned_paths_when_routing_empty(manifest_module) -> None:
    patterns = manifest_module.route_patterns("demo-task")
    assert ("apps/backend/", "backend") in patterns
    assert ("docs/demo.md", "backend") in patterns


def test_lane_route_hints_include_branch_and_path_tokens(manifest_module) -> None:
    hints = manifest_module.lane_route_hints("demo-task")
    backend = hints["backend"]
    assert "backend" in backend
    assert "codex/demo-backend" in backend
    assert "{orchestrator_root}-demo-backend" in backend


def test_merge_order_reads_fixture_manifest(manifest_module) -> None:
    assert manifest_module.merge_order("demo-task") == ["backend", "frontend"]


def test_guidance_fallbacks_read_manifest_policy(manifest_module) -> None:
    fallbacks = manifest_module.guidance_fallbacks("demo-task", "backend")
    assert fallbacks[0]["subject"] == "backend next slice"


def test_task_plan_path_resolves_relative_to_repo_root(manifest_module) -> None:
    path = manifest_module.task_plan_path("demo-task", orchestrator_root="/tmp/context-alt-text-monorepo")
    assert path == "/tmp/context-alt-text-monorepo/docs/tasks/demo-task-plan.md"


def test_heading_to_lane_reads_manifest_mapping(manifest_module) -> None:
    mapping = manifest_module.heading_to_lane("demo-task")
    assert mapping["Phase 1: Backend"] == "backend"


def test_plan_routing_hints_reads_manifest_hints(manifest_module) -> None:
    hints = manifest_module.plan_routing_hints("demo-task")
    assert hints[0]["text_prefix"] == "Backend integration test:"


def test_expand_path_template_replaces_root_placeholder(manifest_module) -> None:
    expanded = manifest_module.expand_path_template(
        "{orchestrator_root}-demo-backend",
        orchestrator_root="/tmp/context-alt-text-monorepo",
    )
    assert expanded == "/tmp/context-alt-text-monorepo-demo-backend"


def test_load_manifest_raises_for_unknown_task(manifest_module) -> None:
    with pytest.raises(FileNotFoundError, match="lane manifest not found"):
        manifest_module.load_manifest("not-a-real-task")


def test_load_manifest_rejects_non_dict_json(tmp_path: Path) -> None:
    module = _load_lane_manifest_module()
    manifest_dir = tmp_path / "lane-orchestration"
    manifest_dir.mkdir()
    bad_manifest = manifest_dir / "bad-task.json"
    bad_manifest.write_text(json.dumps(["not", "an", "object"]))

    original_dir = module.MANIFEST_DIR
    module.MANIFEST_DIR = manifest_dir
    try:
        with pytest.raises(RuntimeError, match="must be a JSON object"):
            module.load_manifest("bad-task")
    finally:
        module.MANIFEST_DIR = original_dir


def test_validate_manifest_rejects_missing_required_keys(tmp_path: Path) -> None:
    module = _load_lane_manifest_module()
    with pytest.raises(RuntimeError, match="missing required top-level key 'merge_order'"):
        module.validate_manifest({"task_ref": "demo-task"}, tmp_path / "demo-task.json")


def test_validate_manifest_rejects_unknown_merge_order_lane(tmp_path: Path) -> None:
    module = _load_lane_manifest_module()
    manifest = {
        "task_ref": "demo-task",
        "merge_order": ["backend", "frontned"],
        "lanes": {
            "backend": {
                "branch": "codex/demo-backend",
                "worktree_path": "{orchestrator_root}-demo-backend",
                "owned_paths": [],
                "test_commands": [],
            }
        },
        "downstream": {"backend": []},
    }
    with pytest.raises(RuntimeError, match="merge_order references unknown lane"):
        module.validate_manifest(manifest, tmp_path / "demo-task.json")


def test_validate_manifest_rejects_unknown_downstream_lane(tmp_path: Path) -> None:
    module = _load_lane_manifest_module()
    manifest = {
        "task_ref": "demo-task",
        "merge_order": ["backend"],
        "lanes": {
            "backend": {
                "branch": "codex/demo-backend",
                "worktree_path": "{orchestrator_root}-demo-backend",
                "owned_paths": [],
                "test_commands": [],
            }
        },
        "downstream": {"backend": ["frontned"]},
    }
    with pytest.raises(RuntimeError, match="downstream for lane 'backend' references unknown lane"):
        module.validate_manifest(manifest, tmp_path / "demo-task.json")


def test_phase5_manifest_smoke_loads_without_error() -> None:
    module = _load_lane_manifest_module()
    manifest = module.load_manifest("phase-5-retention-export-and-audit-controls")
    assert manifest["task_ref"] == "phase-5-retention-export-and-audit-controls"
