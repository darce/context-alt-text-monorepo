from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "agentic" / "consumer-setup.md"

REQUIRED_HEADINGS = (
    "## Prerequisites",
    "## Install",
    "## State Paths",
    "## Update Workflow",
    "## Doctor and Repair",
    "## Git Hooks",
    "## Daemons",
    "## Troubleshooting",
    "## Tenancy",
    "## Platform Support",
)

REQUIRED_SNIPPETS = (
    'git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2',
    'git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.2',
    'git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0',
    "agentic-bootstrap install --target .",
    "agentic-bootstrap update",
    "agentic-bootstrap doctor",
    "agentic-bootstrap repair",
    "AGENT_HANDOFF_WORKSPACE_ROOT",
    "AGENT_HANDOFF_STATE_DIR",
    "AGENT_HANDOFF_DASHBOARD_PATH",
    "AGENT_HANDOFF_CURRENT_TASK_PATH",
    "AGENT_HANDOFF_EXPORTS_DIR",
    "core.hooksPath",
    "scripts/hooks/git",
    "AmbiguousWorkspaceContextError",
    "ConsumerRootResolutionError",
    "orchestrator.daemons.enabled",
    ".task-state/handoff.db",
)

REQUIRED_UPDATE_SNIPPETS = (
    'pip install --upgrade "git+ssh://git@github.com/darce/mcp-agent-handoff.git"',
    'pip install --upgrade "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git"',
    'pip install --upgrade "git+ssh://git@github.com/darce/agentic-bootstrap.git"',
)


def test_consumer_setup_doc_exists_and_is_standalone() -> None:
    assert DOC_PATH.exists(), "docs/agentic/consumer-setup.md is missing"

    text = DOC_PATH.read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"consumer-setup doc is missing heading: {heading}"

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, f"consumer-setup doc is missing required snippet: {snippet}"

    update_section = text.split("## Update Workflow", 1)[1].split("## Doctor and Repair", 1)[0]
    for snippet in REQUIRED_UPDATE_SNIPPETS:
        assert snippet in update_section, f"consumer-setup doc is missing required update snippet: {snippet}"

    assert "--upgrade \"git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2\"" not in update_section
    assert "--upgrade \"git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.2\"" not in update_section
    assert "--upgrade \"git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.2.0\"" not in update_section

    assert "E17-10" not in text, "consumer-setup doc must be standalone, not task-plan dependent"
    assert "task plan" not in text.lower(), "consumer-setup doc must not tell readers to consult the task plan"
