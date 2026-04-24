from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "mcp" / "mcp-server.sh"
README_PATH = REPO_ROOT / "scripts" / "README.md"


def test_obsolete_mcp_server_sh_is_removed() -> None:
    assert not SCRIPT_PATH.exists(), (
        "scripts/mcp/mcp-server.sh still exists even though live MCP runtime "
        "and CI flows already use installed console scripts directly"
    )

    readme = README_PATH.read_text(encoding="utf-8")
    assert "mcp-server.sh" not in readme, (
        "scripts/README.md still documents mcp-server.sh after the runtime cutover"
    )