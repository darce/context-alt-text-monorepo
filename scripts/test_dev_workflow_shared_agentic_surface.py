"""Doc-lock test for `docs/agentic/rules/development-workflow.md § Shared Agentic Surface`.

E17-10 Slice 0 introduces the shared-agentic-surface section that names the
standalone `darce/*` remote repos backing the MVP hoist topology. This test
guards the section's required content so future edits cannot silently drop
remote URLs, the one-way-sync statement, the naming policy, or the post-MVP
TODO anchors that flag the reverse-sync and in-tree-cleanup follow-ons.

The heading match is anchored to a full line (not a substring) and the
section extractor stops at the next heading of the same or higher level so
later sibling subsections cannot be silently absorbed into the locked range.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "agentic" / "rules" / "development-workflow.md"

# The section is rendered as an h3 nested under `## Branch Isolation Protocol`.
# Lock the exact heading level + text and stop at the next h1/h2/h3 boundary.
SECTION_HEADING_LEVEL = 3
SECTION_HEADING_TEXT = "Shared Agentic Surface"
SECTION_HEADING_LINE = f"{'#' * SECTION_HEADING_LEVEL} {SECTION_HEADING_TEXT}"
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S", re.MULTILINE)

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

# The naming policy must be stated explicitly: only MCP server repos carry the
# `mcp-` prefix; the shared-surface and bootstrap repos do not.
REQUIRED_NAMING_POLICY_PHRASES = (
    "mcp-agent-handoff",
    "mcp-agent-orchestrator",
    "agentic-system",
    "agentic-bootstrap",
)


def _shared_agentic_surface_section(text: str) -> str:
    """Return the body of the locked section.

    Matches the heading as a complete line at the configured level and stops
    at the next heading of the same or higher level (so later sibling `###`
    sections cannot bleed into the asserted range).
    """
    lines = text.splitlines(keepends=True)
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        if line.rstrip("\n") == SECTION_HEADING_LINE:
            start_idx = idx + 1
            break
    assert start_idx is not None, (
        f"development-workflow.md is missing required section heading line: "
        f"{SECTION_HEADING_LINE!r}"
    )
    section_lines: list[str] = []
    for line in lines[start_idx:]:
        match = _HEADING_RE.match(line)
        if match and len(match.group(1)) <= SECTION_HEADING_LEVEL:
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

    for repo in REQUIRED_NAMING_POLICY_PHRASES:
        assert repo in section, (
            f"Shared Agentic Surface section is missing canonical repo name: {repo!r}"
        )

    # Guard the naming convention itself: deprecated `mcp-agentic-*` names must
    # never reappear in this locked section.
    assert "mcp-agentic-system" not in section, (
        "Shared Agentic Surface section reintroduced deprecated name `mcp-agentic-system`"
    )
    assert "mcp-agentic-bootstrap" not in section, (
        "Shared Agentic Surface section reintroduced deprecated name `mcp-agentic-bootstrap`"
    )
