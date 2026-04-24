from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_DIR = REPO_ROOT / "packages" / "agent-handoff-mcp"
ORCHESTRATOR_DIR = REPO_ROOT / "packages" / "agent-orchestrator-mcp"


def test_duplicated_local_mcp_package_dirs_are_removed() -> None:
    assert not HANDOFF_DIR.exists(), (
        "packages/agent-handoff-mcp still exists even though runtime, CI, and root helper surfaces are cut over to the standalone package boundary"
    )
    assert not ORCHESTRATOR_DIR.exists(), (
        "packages/agent-orchestrator-mcp still exists even though runtime, CI, and root helper surfaces are cut over to the standalone package boundary"
    )