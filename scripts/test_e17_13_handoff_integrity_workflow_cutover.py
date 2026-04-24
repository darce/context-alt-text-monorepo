from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "handoff-integrity.yml"

REQUIRED_SNIPPETS = (
    'pip install "agent-handoff-mcp @ git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2"',
    'pip install "agent-orchestrator-mcp @ git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3"',
    'python -m agent_orchestrator_mcp.orchestration.handoff_integrity_guard',
)

FORBIDDEN_SNIPPETS = (
    'packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_integrity_guard.py',
    'pip install -e packages/agent-orchestrator-mcp',
    'PYTHONPATH="packages/agent-orchestrator-mcp/src"',
    'python packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/handoff_integrity_guard.py',
)


def test_handoff_integrity_workflow_uses_installed_orchestrator_package() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, (
            f"handoff-integrity workflow is missing required external-runtime snippet: {snippet}"
        )

    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in text, (
            f"handoff-integrity workflow still depends on local orchestrator package source: {snippet}"
        )