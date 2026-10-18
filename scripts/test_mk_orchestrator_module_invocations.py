from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MK_HANDOFF_PATH = REPO_ROOT / "mk" / "handoff.mk"
MK_LANE_GUARDS_PATH = REPO_ROOT / "mk" / "lane-guards.mk"
MK_LANE_LIFECYCLE_PATH = REPO_ROOT / "mk" / "lane-lifecycle.mk"
MK_LANE_WORKER_PATH = REPO_ROOT / "mk" / "lane-worker.mk"
GUARD_SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "handoff_integrity_guard.py"


def test_handoff_integrity_make_target_uses_repo_local_guard() -> None:
    text = MK_HANDOFF_PATH.read_text(encoding="utf-8")

    assert '$(MCP_PYTHON) "$(WORKTREE_ROOT_REAL)/scripts/mcp/handoff_integrity_guard.py"' in text
    assert '-m workbay_orchestrator_mcp.orchestration.handoff_integrity_guard' not in text


def test_remaining_mk_orchestrator_helpers_use_installed_modules() -> None:
    joined = "\n".join(
        (
            MK_HANDOFF_PATH.read_text(encoding="utf-8"),
            MK_LANE_GUARDS_PATH.read_text(encoding="utf-8"),
            MK_LANE_LIFECYCLE_PATH.read_text(encoding="utf-8"),
            MK_LANE_WORKER_PATH.read_text(encoding="utf-8"),
        )
    )

    expected_snippets = (
        '-m workbay_orchestrator_mcp.orchestration.handoff_guidance_summary',
        '-m workbay_orchestrator_mcp.orchestration.review_dispatch',
        # review_runner run: the orchestrator-lane `make review-run` target was
        # removed in MAINT-workstate-migration-20260530 (canonical lifecycle.mk
        # owns review-run now); the lane review_runner is an audited
        # lost-functionality upstream finding, so its invocation no longer appears.
        '-m workbay_orchestrator_mcp.orchestration.generate_lane_manifest',
        '-m workbay_orchestrator_mcp.orchestration.bootstrap_lane',
        '-m workbay_orchestrator_mcp.orchestration.lane_prompt',
        '-m workbay_orchestrator_mcp.orchestration.lane_exec',
        '-m workbay_orchestrator_mcp.orchestration.lane_result handoff',
        '-m workbay_orchestrator_mcp.orchestration.dashboard_live',
        '-m workbay_orchestrator_mcp.orchestration.dashboard_tui',
    )
    for snippet in expected_snippets:
        assert snippet in joined, f"missing installed orchestrator module invocation: {snippet}"

    forbidden_snippets = (
        '$(ORCHESTRATION_DIR)/',
        '$(WORKTREE_ORCHESTRATION_DIR)/',
        '/handoff_guidance_summary.py',
        '/review_dispatch.py',
        '/review_runner.py',
        '/generate_lane_manifest.py',
        '/bootstrap_lane.py',
        '/lane_prompt.py',
        '/lane_exec.py',
        '/lane_result.py',
        '/dashboard_live.py',
        '/dashboard_tui.py',
    )
    for snippet in forbidden_snippets:
        assert snippet not in joined, f"stale orchestrator file-path invocation remains: {snippet}"


def test_repo_local_handoff_integrity_guard_smoke() -> None:
    result = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "handoff-integrity-guard: pass" in result.stdout