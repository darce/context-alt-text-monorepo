from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = REPO_ROOT / "Makefile"

REQUIRED_SNIPPETS = (
    '$(MAKE) check-mcp;',
    'git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.4.2',
    'git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.3',
    'agent-handoff-mcp" --workspace-root "$(WORKTREE_ROOT_REAL)" doctor',
    'agent-orchestrator-mcp" --workspace-root "$(WORKTREE_ROOT_REAL)" --help >/dev/null',
)

FORBIDDEN_SNIPPETS = (
    '$(MAKE) lint-handoff;',
    '$(MAKE) lint-orchestrator;',
    '$(MAKE) test-handoff;',
    '$(MAKE) test-orchestrator;',
    '$(MAKE) format-handoff',
    '$(MAKE) format-orchestrator',
    '$(MAKE) -C packages/agent-handoff-mcp',
    'ORCHESTRATOR_SRC := packages/agent-orchestrator-mcp/src',
    'ORCHESTRATOR_TESTS := packages/agent-orchestrator-mcp/tests',
    'test-handoff:',
    'test-orchestrator:',
    'lint-handoff:',
    'lint-orchestrator:',
    'fix-lint-handoff:',
    'fix-lint-orchestrator:',
    'fix-lint-mcp:',
    'format-handoff:',
    'format-orchestrator:',
    'mypy-handoff:',
    'mypy-orchestrator:',
    'check-handoff:',
    'check-orchestrator:',
)


def test_root_makefile_drops_local_mcp_package_qa_targets() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")

    for snippet in REQUIRED_SNIPPETS:
        assert snippet in text, (
            f"Makefile is missing required external MCP verification snippet: {snippet}"
        )

    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in text, (
            f"Makefile still contains obsolete local MCP package QA snippet: {snippet}"
        )