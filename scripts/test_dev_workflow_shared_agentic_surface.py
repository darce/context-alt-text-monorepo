"""Doc-lock test for `docs/agentic/rules/development-workflow.md § Shared Agentic Surface`.

E17-10 Slice 0 introduces the shared-agentic-surface section that names the
standalone `darce/*` remote repos backing the MVP hoist topology. This test
guards the section's required content so future edits cannot silently drop
remote URLs, the one-way-sync statement, or the post-MVP TODO anchors that
flag the reverse-sync and in-tree-cleanup follow-ons.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "agentic" / "rules" / "development-workflow.md"

SECTION_HEADING = "## Shared Agentic Surface"
NEXT_HEADING_PREFIX = "## "

REQUIRED_REMOTE_URLS = (
    "git@github.com:darce/agentic-system.git",
    "git@github.com:darce/mcp-agent-handoff.git",
    "git@github.com:darce/mcp-agent-orchestrator.git",
    "git@github.com:darce/agentic-bootstrap.git",
)

REQUIRED_TODO_ANCHORS = (
    "TODO(E17-10-POST-MVP-SYNC)",
    "TODO(E17-10-POST-MVP-CLEANUP)",
)

REQUIRED_PHRASES = (
    "one-way",
    "monorepo",
)


def _shared_agentic_surface_section(text: str) -> str:
    assert SECTION_HEADING in text, (
        f"development-workflow.md is missing required section heading: {SECTION_HEADING!r}"
    )
    after = text.split(SECTION_HEADING, 1)[1]
    # Stop at the next top-level `## ` heading (or EOF).
    lines = after.splitlines(keepends=True)
    section_lines: list[str] = []
    for line in lines:
        if line.startswith(NEXT_HEADING_PREFIX) and section_lines:
            break
        section_lines.append(line)
    return "".join(section_lines)


def test_shared_agentic_surface_section_present_and_complete() -> None:
    assert DOC_PATH.exists(), f"missing doc: {DOC_PATH}"
    text = DOC_PATH.read_text(encoding="utf-8")
    section = _shared_agentic_surface_section(text)

    for url in REQUIRED_REMOTE_URLS:
        assert url in section, (
            f"Shared Agentic Surface section is missing remote URL: {url!r}"
        )

    for anchor in REQUIRED_TODO_ANCHORS:
        assert anchor in section, (
            f"Shared Agentic Surface section is missing required TODO anchor: {anchor!r}"
        )

    lowered = section.lower()
    for phrase in REQUIRED_PHRASES:
        assert phrase in lowered, (
            f"Shared Agentic Surface section is missing required phrase: {phrase!r}"
        )
