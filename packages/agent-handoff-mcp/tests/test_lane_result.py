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

    commands = lane_result._build_command_plan(
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

    assert commands[0] == ["make", "-f", "/repo/Makefile", "-C", "/repo-frontend", "lane-commit", "TASK=task-1", "LANE=frontend"]
    assert commands[1] == ["make", "-f", "/repo/Makefile", "-C", "/repo-frontend", "lane-status", "TASK=task-1", "LANE=frontend"]
    report_cmd = commands[2]
    assert report_cmd[:2] == ["/repo/scripts/worktree-lane", "report"]
    assert "--merge-ready" in report_cmd
    assert "--summary" in report_cmd
    assert "frontend slice ready" in report_cmd
    assert report_cmd.count("--test-command") == 2
    assert "npm run test" in report_cmd
    assert "npm run typecheck" in report_cmd
    assert "Implemented the assigned test coverage." in report_cmd


def test_build_make_command_for_guidance_without_commits() -> None:
    lane_result = _load_lane_result_module()

    commands = lane_result._build_command_plan(
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

    assert len(commands) == 1
    report_cmd = commands[0]
    assert report_cmd[:2] == ["/repo/scripts/worktree-lane", "report"]
    assert "--status" in report_cmd
    assert "blocked" in report_cmd
    assert report_cmd.count("--test-command") == 1
    assert "pg_isready -h localhost -p 5432" in report_cmd
    assert report_cmd.count("--blocker") == 1
    assert "pytest could not create temp files" in report_cmd
    assert "The fixes appear present already, but verification could not complete." in report_cmd
