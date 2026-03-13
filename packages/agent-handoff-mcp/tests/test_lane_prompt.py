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
