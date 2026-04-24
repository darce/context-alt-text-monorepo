from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "mcp-packages.yml"


def test_obsolete_local_mcp_packages_workflow_is_removed() -> None:
    assert not WORKFLOW_PATH.exists(), (
        "mcp-packages.yml still exists even though Slice 3 has moved live MCP CI "
        "verification to installed standalone package flows"
    )