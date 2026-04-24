from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = REPO_ROOT / "Makefile"
MK_ORCHESTRATOR_PATH = REPO_ROOT / "mk" / "orchestrator.mk"
CHECK_CONTEXT_PATH = REPO_ROOT / "scripts" / "check-task-context.py"
MAINT_ARCHIVE_PATH = REPO_ROOT / "scripts" / "maint_archive_stale.py"
WORKTREE_AUDIT_PATH = REPO_ROOT / "scripts" / "worktree_audit.py"
SCRIPTS_README_PATH = REPO_ROOT / "scripts" / "README.md"

FORBIDDEN_SNIPPETS = (
    "packages/agent-handoff-mcp/src",
    "packages/agent-orchestrator-mcp/src",
    "packages/agent-orchestrator-mcp).",
    "ORCHESTRATION_DIR :=",
    "WORKTREE_ORCHESTRATION_DIR :=",
)

REQUIRED_MAKEFILE_SNIPPETS = (
    "LANE_CONFIG_CMD = $(MCP_PYTHON) -m agent_orchestrator_mcp.orchestration.lane_config",
    'dashboard:\n\t@$(MCP_CMD) $(MCP_STATE_ARGS) render-handoff --kind dashboard',
    'context:\n\t@$(MCP_PYTHON) scripts/check-task-context.py',
    'worktree-audit:\n\t@$(MCP_PYTHON) scripts/worktree_audit.py',
    'maint-archive-stale:\n\t@$(MCP_PYTHON) scripts/maint_archive_stale.py $(MAINT_ARCHIVE_ARGS)',
)


def test_runtime_orchestration_helpers_drop_local_mcp_package_paths() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    mk_orchestrator = MK_ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    check_context = CHECK_CONTEXT_PATH.read_text(encoding="utf-8")
    maint_archive = MAINT_ARCHIVE_PATH.read_text(encoding="utf-8")
    worktree_audit = WORKTREE_AUDIT_PATH.read_text(encoding="utf-8")
    scripts_readme = SCRIPTS_README_PATH.read_text(encoding="utf-8")

    for snippet in REQUIRED_MAKEFILE_SNIPPETS:
        assert snippet in makefile, (
            f"Makefile is missing required runtime/orchestration cutover snippet: {snippet}"
        )

    for text in (
        makefile,
        mk_orchestrator,
        check_context,
        maint_archive,
        worktree_audit,
        scripts_readme,
    ):
        for snippet in FORBIDDEN_SNIPPETS:
            assert snippet not in text, (
                f"runtime/orchestration helper still depends on local MCP package path: {snippet}"
            )


def test_installed_runtime_helpers_execute_without_local_package_dirs() -> None:
    lane_config = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_orchestrator_mcp.orchestration.lane_config",
            "list-tasks",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert lane_config.returncode == 0, lane_config.stderr or lane_config.stdout

    context = subprocess.run(
        [sys.executable, str(CHECK_CONTEXT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert context.returncode == 0, context.stderr or context.stdout
    assert "Context aligned" in context.stdout