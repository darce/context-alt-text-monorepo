from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS_PATH = REPO_ROOT / ".github" / "copilot-instructions.md"

FORBIDDEN_SNIPPETS = (
    "For `packages/agent-handoff-mcp` and `packages/agent-orchestrator-mcp`",
    "PYTHONPATH=packages/agent-handoff-mcp/src python3 -c",
    "Running in monorepo without install:",
)

REQUIRED_SNIPPETS = (
    "For external MCP package verification and runtime flows, do not invoke IDE Python environment-configuration tools.",
    "Running against the installed MCP package:",
    'pyenv exec python -c "',
    "from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state",
)


def test_copilot_instructions_drop_local_mcp_package_guidance() -> None:
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, (
            f"copilot instructions are missing required external-runtime snippet: {snippet}"
        )

    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in text, (
            f"copilot instructions still depend on local MCP package guidance: {snippet}"
        )