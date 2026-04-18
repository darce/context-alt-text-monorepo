from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

from agent_orchestrator_mcp.orchestration.handoff_read_shapes import open_handoff_items_kwargs

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "review_dispatch.py"


def _load_review_dispatch_module():
    spec = importlib.util.spec_from_file_location("review_dispatch", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load review_dispatch module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_routes_review_findings_by_owned_path() -> None:
    module = _load_review_dispatch_module()

    lane_id = module._route_issue(
        "phase-5-retention-export-and-audit-controls",
        "review_findings",
        {
            "finding_id": "P5-HTTP-01",
            "file_path": "apps/prototype-description-service/recognition/interface_adapters/http/routers/retention.py",
        },
    )

    assert lane_id == "backend-http"


def test_routes_backend_domain_unit_test_findings_by_owned_path() -> None:
    module = _load_review_dispatch_module()

    lane_id = module._route_issue(
        "phase-5-retention-export-and-audit-controls",
        "review_findings",
        {
            "finding_id": "P5-DOM-UT-01",
            "file_path": "apps/prototype-description-service/recognition/tests/unit/test_purge_service.py",
        },
    )

    assert lane_id == "backend-domain"


def test_routes_blockers_by_lane_hint_text() -> None:
    module = _load_review_dispatch_module()

    lane_id = module._route_issue(
        "phase-5-retention-export-and-audit-controls",
        "blockers",
        {
            "id": 7,
            "description": (
                "Backend-http lane blocker: current mypy failures are in out-of-scope test files "
                "under apps/prototype-description-service/recognition/tests/."
            ),
        },
    )

    assert lane_id == "backend-http"


def test_routes_actions_by_worktree_path_hint() -> None:
    module = _load_review_dispatch_module()

    lane_id = module._route_issue(
        "phase-5-retention-export-and-audit-controls",
        "actions",
        {
            "id": 72,
            "action": (
                "Backend domain/schema lane: implement Phase 0-2 backend models, migration, "
                "repositories, services, and pytest coverage in "
                "/Users/daniel/Development/context-alt-text-monorepo-p5-backend-domain "
                "(branch codex/p5-backend-domain)."
            ),
        },
    )

    assert lane_id == "backend-domain"


def test_leaves_multi_lane_actions_unassigned() -> None:
    module = _load_review_dispatch_module()

    lane_id = module._route_issue(
        "phase-5-retention-export-and-audit-controls",
        "actions",
        {
            "id": 74,
            "action": (
                "Phase 1/3 next slice: implement backend retention policy persistence and real "
                "retention HTTP responses on the backend-domain and backend-http worktrees."
            ),
        },
    )

    assert lane_id is None


def test_load_open_handoff_items_requests_only_dispatch_sections() -> None:
    module = _load_review_dispatch_module()
    mock_ahm = mock.MagicMock()
    mock_ahm.get_handoff_state.return_value = {
        "ok": True,
        "findings_open": [{"finding_id": "F-1"}],
        "blockers_open": [{"id": 2}],
        "actions_pending": [{"id": 3}],
    }

    with mock.patch.dict(__import__("sys").modules, {"agent_handoff_mcp": mock_ahm}):
        issue_sets = module._load_open_handoff_items("task-ref")

    assert issue_sets == {
        "review_findings": [{"finding_id": "F-1"}],
        "blockers": [{"id": 2}],
        "actions": [{"id": 3}],
    }
    mock_ahm.get_handoff_state.assert_called_once_with(**open_handoff_items_kwargs("task-ref"))
