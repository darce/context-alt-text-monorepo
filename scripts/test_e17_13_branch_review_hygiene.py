from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
PLAN_PATH = REPO_ROOT / "docs" / "tasks" / "17.0" / "E17-13-hoisted-surface-cleanup-task-plan.md"

EXPECTED_MCP_STATE_ARGS = (
    'MCP_STATE_ARGS = --workspace-root "$(ORCHESTRATOR_ROOT)" '
    '--state-dir "$(ORCHESTRATOR_ROOT)/.task-state" '
    '--current-task-path "$(ORCHESTRATOR_ROOT)/CURRENT_TASK.json" '
    '--exports-dir "$(ORCHESTRATOR_ROOT)/.task-state/exports"'
)

EXPECTED_SLICE_1_CHECKLIST = (
    "- [x] Verified all four external repos are reachable over SSH.",
    "- [x] Confirmed selected refs/tags/SHAs for `mcp-agent-handoff`, `mcp-agent-orchestrator`, `agentic-system`, and `agentic-bootstrap`.",
    "- [x] Test-installed `agentic-bootstrap@v0.2.0` first; only triggered recovery/republish if the tag install failed.",
    "- [x] Wrote `docs/assessments/e17-13-hoisted-surface-inventory.md` with owner classification and deletion gates.",
    "- [x] Classified every `packages/*` directory, including `codex-subagent-bridge` and `shared-contracts`.",
    "- [x] Decided ownership of `scripts/generate_agent_workflows.py` and the `generate-agent-workflows` / `check-agent-workflows` targets.",
    "- [x] Recorded verification evidence in handoff.",
)

EXPECTED_PROVENANCE_NOTE = (
    "For Slice 2+ handoff writes, capture `git rev-parse HEAD` from the feature worktree",
    "pass that SHA as `actor.commit_sha`",
    "Do not rely on the root worktree's ambient HEAD.",
)


def test_e17_13_branch_review_hygiene_is_locked() -> None:
    makefile_text = MAKEFILE_PATH.read_text(encoding="utf-8")
    plan_text = PLAN_PATH.read_text(encoding="utf-8")

    assert EXPECTED_MCP_STATE_ARGS in makefile_text, (
        "E17-13 review hygiene expects the feature branch Makefile to keep "
        "MCP_STATE_ARGS anchored to ORCHESTRATOR_ROOT so linked-worktree "
        "doctor/state behavior stays consistent with RuntimeConfig.for_repo()"
    )

    for line in EXPECTED_SLICE_1_CHECKLIST:
        assert line in plan_text, f"Slice 1 checklist is missing completed item: {line}"

    for snippet in EXPECTED_PROVENANCE_NOTE:
        assert snippet in plan_text, (
            f"task plan is missing handoff provenance discipline note: {snippet}"
        )