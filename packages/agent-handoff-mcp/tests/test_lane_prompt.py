from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "lane_prompt.py"


def _load_lane_prompt_module():
    spec = importlib.util.spec_from_file_location("lane_prompt", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_prompt module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_prompt_returns_no_work_message_when_lane_is_idle() -> None:
    module = _load_lane_prompt_module()

    prompt = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
    )

    assert prompt == module.NO_WORK_MESSAGE


def test_build_prompt_includes_messages_actions_and_findings() -> None:
    module = _load_lane_prompt_module()

    prompt = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Phase 5 backend-domain slice."},
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                }
            ],
            "actions": [
                {
                    "id": 72,
                    "status": "pending",
                    "priority": 1,
                    "action": "Implement the backend-domain slice.",
                }
            ],
            "blockers": [],
            "findings": [
                {
                    "finding_id": "P5-IMPL-01",
                    "status": "open",
                    "severity": "medium",
                    "file_path": "docs/tasks/phase5.md",
                    "line_start": 411,
                    "description": "Checklist item is still unchecked.",
                }
            ],
            "reports": [{"status": "submitted", "summary": "backend-domain lane ready for orchestrator review."}],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
    )

    assert "Open orchestrator messages:" in prompt
    assert "Pending lane actions:" in prompt
    assert "Open lane review findings:" in prompt
    assert "make lane-handoff" in prompt


def test_build_summary_lines_color_codes_actionable_items() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines(
        {
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                }
            ],
            "actions": [
                {"id": 72, "status": "pending", "priority": 1, "action": "Implement the backend-domain slice."}
            ],
            "blockers": [
                {"id": 5, "status": "open", "description": "Database not reachable."}
            ],
            "findings": [
                {
                    "finding_id": "P5-IMPL-01",
                    "status": "open",
                    "severity": "medium",
                    "file_path": "docs/tasks/phase5.md",
                    "line_start": 411,
                    "description": "Checklist item is still unchecked.",
                }
            ],
        }
    )

    assert any("[BLOCKER]" in line and "\x1b[" in line for line in lines)
    assert any("[ACTION P1]" in line and "\x1b[" in line for line in lines)
    assert any("[REVIEW MEDIUM]" in line and "\x1b[" in line for line in lines)
    assert any("[MESSAGE]" in line and "\x1b[" in line for line in lines)


def test_build_summary_lines_idle_message() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines({"messages": [], "actions": [], "blockers": [], "findings": []})
    assert len(lines) == 1
    assert "[IDLE]" in lines[0]


def test_build_prompt_waits_when_worker_handoff_is_newer_than_open_work() -> None:
    module = _load_lane_prompt_module()

    prompt = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                    "updated_at": "2026-03-15 16:00:00",
                },
                {
                    "id": 26,
                    "direction": "worker_to_orchestrator",
                    "status": "open",
                    "subject": "backend-domain needs guidance",
                    "message": "Already reported back to orchestrator.",
                    "updated_at": "2026-03-15 17:42:46",
                },
            ],
            "actions": [{"id": 72, "status": "pending", "priority": 1, "action": "Implement the backend-domain slice.", "updated_at": "2026-03-15 16:00:00"}],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
    )

    assert prompt == module.WAITING_MESSAGE


def test_build_summary_lines_waiting_when_worker_handoff_is_open_and_newer() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines(
        {
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                    "updated_at": "2026-03-15 16:00:00",
                },
                {
                    "id": 26,
                    "direction": "worker_to_orchestrator",
                    "status": "open",
                    "subject": "backend-domain needs guidance",
                    "message": "Already reported back to orchestrator.",
                    "updated_at": "2026-03-15 17:42:46",
                },
            ],
            "actions": [{"id": 72, "status": "pending", "priority": 1, "action": "Implement the backend-domain slice.", "updated_at": "2026-03-15 16:00:00"}],
            "blockers": [],
            "findings": [],
        }
    )

    assert len(lines) == 1
    assert "[WAITING]" in lines[0]
