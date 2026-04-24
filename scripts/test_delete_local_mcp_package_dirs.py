from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_DIR = REPO_ROOT / "packages" / "agent-handoff-mcp"
ORCHESTRATOR_DIR = REPO_ROOT / "packages" / "agent-orchestrator-mcp"
LIVE_SURFACE_ROOTS = (
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "Makefile",
    REPO_ROOT / "docs" / "agentic",
    REPO_ROOT / "mk",
    REPO_ROOT / "scripts",
)
DELETED_PACKAGE_LITERALS = (
    "packages/" + "agent-handoff-mcp",
    "packages/" + "agent-orchestrator-mcp",
)


def test_duplicated_local_mcp_package_dirs_are_removed() -> None:
    assert not HANDOFF_DIR.exists(), (
        "packages/agent-handoff-mcp still exists even though runtime, CI, and root helper surfaces are cut over to the standalone package boundary"
    )
    assert not ORCHESTRATOR_DIR.exists(), (
        "packages/agent-orchestrator-mcp still exists even though runtime, CI, and root helper surfaces are cut over to the standalone package boundary"
    )


def test_live_agentic_surfaces_do_not_reference_deleted_mcp_package_dirs() -> None:
    offenders: list[str] = []
    for root in LIVE_SURFACE_ROOTS:
        paths = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT)
            if rel.match("scripts/test_*.py") or rel.match("scripts/hooks/test_*.py"):
                continue
            if "__pycache__" in rel.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for literal in DELETED_PACKAGE_LITERALS:
                if literal in text:
                    offenders.append(f"{rel}: {literal}")

    assert offenders == []
