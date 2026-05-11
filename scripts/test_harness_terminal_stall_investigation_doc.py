from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "operator" / "harness-terminal-stall-investigation.md"


def test_harness_terminal_stall_doc_records_public_signals_and_fix() -> None:
    text = DOC_PATH.read_text(encoding="utf-8")

    required_snippets = (
        "anthropics/claude-code#52933",
        "anthropics/claude-code#57260",
        "microsoft/vscode#315395",
        "does **not** confirm that zsh is the root cause",
        'terminal.integrated.agentHostProfile.osx',
        '"path": "/bin/bash"',
        "single focused terminal command per invocation",
    )

    for snippet in required_snippets:
        assert snippet in text, f"missing investigation doc snippet: {snippet}"
