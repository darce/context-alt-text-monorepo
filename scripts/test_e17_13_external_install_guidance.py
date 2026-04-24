from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

CLAUDE_PATH = REPO_ROOT / "CLAUDE.md"
INSTRUCTIONS_PATH = REPO_ROOT / "docs" / "agentic" / "instructions.md"
WORKFLOW_RULE_PATH = REPO_ROOT / "docs" / "agentic" / "rules" / "development-workflow.md"
TESTING_RULE_PATH = REPO_ROOT / "docs" / "agentic" / "rules" / "testing-python.md"
PLAN_PATH = REPO_ROOT / "docs" / "tasks" / "17.0" / "E17-13-hoisted-surface-cleanup-task-plan.md"

LEGACY_GUIDANCE_SNIPPETS = (
    "cd packages/agent-handoff-mcp && make test-handoff",
    "cd packages/agent-orchestrator-mcp && make test-orchestrator",
)

REQUIRED_FILE_SNIPPETS = {
    CLAUDE_PATH: (
        "External MCP Package Verification",
        'git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2',
        'git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3',
        'agent-handoff-mcp --workspace-root . doctor',
        'agent-orchestrator-mcp --workspace-root . --help',
    ),
    INSTRUCTIONS_PATH: (
        "Python (external MCP package verification):",
        "scratch venv",
        "standalone `git+ssh://` refs",
        "Do not use `make test-handoff` or `make test-orchestrator` for this cleanup verification path.",
    ),
    WORKFLOW_RULE_PATH: (
        "External-install verification note:",
        "pinned `pip install` from the standalone repos in a scratch venv",
        "CLI/import smoke checks",
        "not the old package-local Makefile guard guidance",
    ),
    TESTING_RULE_PATH: (
        "## External MCP Package Verification (E17-13)",
        "scratch venv",
        "no editable installs from this monorepo",
        'git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2',
        'git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3',
    ),
    PLAN_PATH: (
        "- [x] Replaced package-local conftest/Makefile guard guidance with external-install verification guidance.",
    ),
}


def test_e17_13_external_install_guidance_is_locked() -> None:
    for path, snippets in REQUIRED_FILE_SNIPPETS.items():
        text = path.read_text(encoding="utf-8")

        for snippet in snippets:
            assert snippet in text, f"{path} is missing required guidance snippet: {snippet}"

        if path != PLAN_PATH:
            for legacy in LEGACY_GUIDANCE_SNIPPETS:
                assert legacy not in text, (
                    f"{path} still contains legacy package-local guidance: {legacy}"
                )