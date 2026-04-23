from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "assessments" / "e17-13-hoisted-surface-inventory.md"

REQUIRED_HEADINGS = (
    "## Objective",
    "## Selected External Refs",
    "## Remote Ref Evidence",
    "## Scratch Install Gate",
    "## Package Classification",
    "## Deletion Gate Matrix",
    "## Generator Ownership Decision",
)

REQUIRED_SNIPPETS = (
    "darce/mcp-agent-handoff",
    "darce/mcp-agent-orchestrator",
    "darce/agentic-system",
    "darce/agentic-bootstrap",
    "v0.4.2",
    "v0.1.3",
    "v0.2.1",
    "v0.2.0",
    "packages/agent-handoff-mcp/",
    "packages/agent-orchestrator-mcp/",
    "packages/codex-subagent-bridge/",
    "packages/shared-contracts/",
    "scripts/generate_agent_workflows.py",
    "git ls-remote --heads --tags",
    "agent-handoff-mcp --workspace-root . doctor",
    "agent-orchestrator-mcp --workspace-root . --help",
    "agentic-bootstrap install --target",
    "Resolved commit SHA",
    "pending `git ls-remote` capture",
    "pending scratch install proof",
    "No deletion slice may start while any Slice 1 prerequisite remains pending.",
)

REQUIRED_CLASSIFICATIONS = (
    "external-owned duplicate",
    "monorepo-local package",
    "bootstrap-managed shared surface input",
)

REQUIRED_GENERATOR_DECISION = (
    "Retain in monorepo as a local driver",
    "generated outputs",
    "external workflow definitions",
)


def test_e17_13_inventory_assessment_exists_and_locks_slice_1_inputs() -> None:
    assert DOC_PATH.exists(), f"missing assessment: {DOC_PATH}"

    text = DOC_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"inventory assessment is missing heading: {heading}"

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, f"inventory assessment is missing required snippet: {snippet}"

    for classification in REQUIRED_CLASSIFICATIONS:
        assert classification in text, (
            f"inventory assessment is missing classification label: {classification}"
        )

    for snippet in REQUIRED_GENERATOR_DECISION:
        assert snippet in text, (
            f"inventory assessment is missing generator decision detail: {snippet}"
        )