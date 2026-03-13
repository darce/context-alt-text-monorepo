from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_lane_result_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "mcp" / "lane_result.py"
    spec = importlib.util.spec_from_file_location("lane_result", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_make_command_for_merge_ready() -> None:
    lane_result = _load_lane_result_module()

    cmd = lane_result._build_make_command(
        orchestrator_root=Path("/repo"),
        task_ref="task-1",
        lane_id="frontend",
        session="task-1-frontend",
        worktree_path=Path("/repo-frontend"),
        result={
            "handoff_action": "merge_ready",
            "summary": "frontend slice ready",
            "details": "Implemented the assigned test coverage.",
            "tests_run": ["npm run test", "npm run typecheck"],
            "blockers": [],
        },
    )

    assert cmd[:5] == ["make", "-f", "/repo/Makefile", "-C", "/repo-frontend"]
    assert "lane-handoff" in cmd
    assert "TASK=task-1" in cmd
    assert "LANE=frontend" in cmd
    assert "SUMMARY=frontend slice ready" in cmd
    assert any(item.startswith("MESSAGE=Implemented the assigned test coverage. Tests run: npm run test; npm run typecheck") for item in cmd)


def test_build_make_command_for_guidance_without_commits() -> None:
    lane_result = _load_lane_result_module()

    cmd = lane_result._build_make_command(
        orchestrator_root=Path("/repo"),
        task_ref="task-1",
        lane_id="backend-domain",
        session="task-1-backend-domain",
        worktree_path=Path("/repo-backend-domain"),
        result={
            "handoff_action": "needs_guidance",
            "summary": "verification blocked by sandbox",
            "details": "The fixes appear present already, but verification could not complete.",
            "tests_run": ["pg_isready -h localhost -p 5432"],
            "blockers": ["pytest could not create temp files"],
        },
    )

    assert "lane-report" in cmd
    assert "STATUS=blocked" in cmd
    assert "MERGE_READY=0" in cmd
    assert any(item.startswith("MESSAGE=The fixes appear present already, but verification could not complete. Tests run: pg_isready -h localhost -p 5432 Blockers: pytest could not create temp files") for item in cmd)
