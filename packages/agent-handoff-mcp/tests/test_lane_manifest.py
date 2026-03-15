from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "lane_manifest.py"


def _load_lane_manifest_module():
    spec = importlib.util.spec_from_file_location("lane_manifest", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_manifest module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_list_task_refs_includes_phase5_manifest() -> None:
    module = _load_lane_manifest_module()

    task_refs = module.list_task_refs()

    assert "phase-5-retention-export-and-audit-controls" in task_refs


def test_infer_lane_from_branch_uses_manifest_branch_mapping() -> None:
    module = _load_lane_manifest_module()

    lane_id = module.infer_lane_from_branch(
        "codex/p5-backend-http",
        "phase-5-retention-export-and-audit-controls",
    )

    assert lane_id == "backend-http"


def test_get_lane_config_expands_worktree_template() -> None:
    module = _load_lane_manifest_module()

    lane = module.get_lane_config(
        "phase-5-retention-export-and-audit-controls",
        "frontend",
        orchestrator_root="/tmp/context-alt-text-monorepo",
    )

    assert lane is not None
    assert lane["worktree_path"] == "/tmp/context-alt-text-monorepo-p5-frontend"
    assert lane["branch"] == "codex/p5-frontend"


def test_route_patterns_reads_manifest_routes() -> None:
    module = _load_lane_manifest_module()

    patterns = module.route_patterns("phase-5-retention-export-and-audit-controls")

    assert ("apps/prototype-description-service/recognition/interface_adapters/http/", "backend-http") in patterns


def test_lane_route_hints_include_branch_and_path_tokens() -> None:
    module = _load_lane_manifest_module()

    hints = module.lane_route_hints("phase-5-retention-export-and-audit-controls")

    backend_http = hints["backend-http"]
    assert "backend-http" in backend_http
    assert "codex/p5-backend-http" in backend_http
    assert "{orchestrator_root}-p5-backend-http" in backend_http


def test_merge_order_reads_manifest_order() -> None:
    module = _load_lane_manifest_module()

    order = module.merge_order("phase-5-retention-export-and-audit-controls")

    assert order == ["backend-domain", "backend-http", "wp-proxy", "frontend"]


def test_expand_path_template_replaces_root_placeholder() -> None:
    module = _load_lane_manifest_module()

    expanded = module.expand_path_template(
        "{orchestrator_root}-p5-backend-http",
        orchestrator_root="/tmp/context-alt-text-monorepo",
    )

    assert expanded == "/tmp/context-alt-text-monorepo-p5-backend-http"


def test_load_manifest_raises_for_unknown_task() -> None:
    module = _load_lane_manifest_module()

    import pytest

    with pytest.raises(FileNotFoundError, match="lane manifest not found"):
        module.load_manifest("not-a-real-task")


def test_load_manifest_rejects_non_dict_json(tmp_path: Path) -> None:
    module = _load_lane_manifest_module()
    manifest_dir = tmp_path / "lane-orchestration"
    manifest_dir.mkdir()
    bad_manifest = manifest_dir / "bad-task.json"
    bad_manifest.write_text(json.dumps(["not", "an", "object"]))

    original_dir = module.MANIFEST_DIR
    module.MANIFEST_DIR = manifest_dir
    try:
        import pytest

        with pytest.raises(RuntimeError, match="must be a JSON object"):
            module.load_manifest("bad-task")
    finally:
        module.MANIFEST_DIR = original_dir
