from __future__ import annotations

from pathlib import Path

from scripts.generate_agent_workflows import (
    CODEX_ROUTER_BEGIN,
    CODEX_ROUTER_END,
    GENERATOR_TAG,
    _check_outputs,
    _expected_outputs,
    _sync_codex_router_consumers,
)


def _manifest() -> dict:
    return {
        "version": 1,
        "commands": [
            {
                "command_id": "branch-review",
                "skill": "branch-review",
                "makefile_target": "make review-run",
                "description": "Implementation branch review workflow.",
                "execution_context": "Use for implementation branch diffs.",
                "argument_schema": [],
                "loop": ["run the branch review checklist"],
            },
            {
                "command_id": "planning-review",
                "skill": "planning-review",
                "makefile_target": "make plan-review DOC=<path>",
                "description": "Formal planning review workflow.",
                "execution_context": "Use for planning artifacts before implementation.",
                "argument_schema": [
                    {
                        "name": "doc",
                        "required": True,
                        "description": "Planning document path to review.",
                    }
                ],
                "loop": ["record findings and verdict in MCP"],
            },
        ],
    }


def test_expected_outputs_include_codex_router_artifact(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"

    outputs = _expected_outputs(_manifest(), claude_out, prompts_out, codex_out)

    router_path = codex_out / "codex-command-router.md"
    assert router_path in outputs
    assert outputs[router_path].startswith(GENERATOR_TAG)
    assert "/branch-review" in outputs[router_path]
    assert "/planning-review" in outputs[router_path]


def test_check_outputs_fails_when_codex_router_is_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    claude_out = repo / ".claude" / "commands"
    prompts_out = repo / ".github" / "prompts"
    codex_out = repo / "docs" / "agentic" / "generated"
    outputs = _expected_outputs(_manifest(), claude_out, prompts_out, codex_out)

    for path, content in outputs.items():
        if path == codex_out / "codex-command-router.md":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    exit_code = _check_outputs(outputs, claude_out, prompts_out, codex_out)

    assert exit_code == 1


def test_sync_codex_router_consumers_rewrites_marked_blocks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    instructions = repo / "docs" / "agentic" / "instructions.md"
    claude = repo / "CLAUDE.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(
        "## Portable Command Router\n\n"
        f"{CODEX_ROUTER_BEGIN}\nold\n{CODEX_ROUTER_END}\n"
    )
    claude.write_text(
        "## Key Triggers\n\n"
        f"{CODEX_ROUTER_BEGIN}\nold\n{CODEX_ROUTER_END}\n"
    )

    failures = _sync_codex_router_consumers(_manifest(), repo, check=False)

    assert failures == []
    assert "/branch-review" in instructions.read_text()
    assert "/planning-review" in claude.read_text()


def test_check_codex_router_consumers_detects_drift(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    instructions = repo / "docs" / "agentic" / "instructions.md"
    claude = repo / "CLAUDE.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(
        "## Portable Command Router\n\n"
        f"{CODEX_ROUTER_BEGIN}\nwrong\n{CODEX_ROUTER_END}\n"
    )
    claude.write_text(
        "## Key Triggers\n\n"
        f"{CODEX_ROUTER_BEGIN}\nwrong\n{CODEX_ROUTER_END}\n"
    )

    failures = _sync_codex_router_consumers(_manifest(), repo, check=True)

    assert len(failures) == 2