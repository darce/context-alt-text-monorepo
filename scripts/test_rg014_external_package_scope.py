from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_PATH = REPO_ROOT / "CLAUDE.md"
CONSTITUTION_PATH = REPO_ROOT / "docs" / "workstate" / "constitution.md"

REQUIRED_SCOPE = (
    "Scope: the standalone `workstate-orchestrator-mcp` package available to the active workspace."
)
FORBIDDEN_SCOPE = "Scope: `packages/workstate-orchestrator-mcp/`."


def test_rg014_scope_tracks_standalone_orchestrator_boundary() -> None:
    for path in (CLAUDE_PATH, CONSTITUTION_PATH):
        text = path.read_text(encoding="utf-8")

        assert REQUIRED_SCOPE in text, (
            f"{path} is missing the standalone orchestrator scope wording for rg-014"
        )
        assert FORBIDDEN_SCOPE not in text, (
            f"{path} still points rg-014 at the deleted monorepo package path"
        )