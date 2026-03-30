"""Tests for scripts/mcp/orchestrator_guidance.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "orchestrator_guidance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("orchestrator_guidance", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load orchestrator_guidance module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_guidance_marks_review_when_work_is_already_satisfied() -> None:
    mod = _load_module()

    resolution = mod._classify_guidance(
        task_ref="daemon-9",
        worker_message={
            "id": 11,
            "lane_id": "backend-http",
            "subject": "backend-http status",
            "message": "This slice already appears resolved in the current branch state.",
        },
        latest_report=None,
        activity={"actions": [], "lane": {"objective": "Ship the backend-http slice."}},
        open_dispatches=[{"id": 41, "direction": "orchestrator_to_worker"}],
    )

    assert resolution.kind == "review"
    assert resolution.lane_status == "review"
    assert resolution.close_dispatch_ids == (41,)


def test_classify_guidance_redispatches_pending_lane_action() -> None:
    mod = _load_module()

    resolution = mod._classify_guidance(
        task_ref="daemon-9",
        worker_message={
            "id": 12,
            "lane_id": "backend-http",
            "subject": "backend-http status",
            "message": "The previous slice is already resolved; highest-priority open lane-owned gap is still pending.",
        },
        latest_report=None,
        activity={
            "actions": [
                {"id": 2, "priority": 2, "status": "pending", "action": "Wire the export response envelope."},
            ],
            "lane": {"objective": "Ship the backend-http slice."},
        },
        open_dispatches=[],
    )

    assert resolution.kind == "redispatch"
    assert resolution.lane_status == "active"
    assert resolution.dispatch_subject == "backend-http next assignment"
    assert resolution.dispatch_message == "Wire the export response envelope."


def test_classify_guidance_marks_environment_blockers_blocked() -> None:
    mod = _load_module()

    with mock.patch.object(mod, "_resolve_next_assignment", return_value=None):
        resolution = mod._classify_guidance(
            task_ref="daemon-9",
            worker_message={
                "id": 13,
                "lane_id": "backend-domain",
                "subject": "backend-domain blocked",
                "message": "PostgreSQL is not running and the sandbox has no usable temporary directory.",
            },
            latest_report=None,
            activity={"actions": [], "lane": {"objective": "Verify reset/bootstrap."}},
            open_dispatches=[],
        )

    assert resolution.kind == "blocked"
    assert resolution.lane_status == "blocked"


def test_resolve_guidance_cycle_dedupes_to_newest_worker_message_per_lane(tmp_path: Path) -> None:
    mod = _load_module()

    older = {
        "id": 20,
        "lane_id": "frontend",
        "session": "older",
        "subject": "frontend status",
        "message": "already resolved",
        "created_at": "2026-03-18 10:00:00",
    }
    newer = {
        "id": 21,
        "lane_id": "frontend",
        "session": "newer",
        "subject": "frontend status",
        "message": "already resolved",
        "created_at": "2026-03-18 10:05:00",
    }

    with (
        mock.patch.object(mod, "_list_open_worker_guidance", return_value=[older, newer]),
        mock.patch.object(mod, "_latest_lane_report", return_value=None),
        mock.patch.object(mod, "_lane_activity", return_value={"actions": [], "lane": {"objective": "Frontend lane"}}),
        mock.patch.object(mod, "_list_open_dispatch_messages", return_value=[]),
        mock.patch.object(mod, "_apply_guidance_resolution", side_effect=lambda **kwargs: kwargs["resolution"]),
    ):
        results = mod._resolve_guidance_cycle(tmp_path, "daemon-9", dry_run=True)

    assert len(results) == 1
    assert results[0].worker_message_id == 21
    assert results[0].kind == "review"
