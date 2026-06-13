from __future__ import annotations

import json
from pathlib import Path

from scripts.smoke_agent_workflows import smoke_agent_workflows


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    manifest = repo / "config" / "agent-workflows" / "portable_commands.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "commands": [
                    {
                        "command_id": "branch-lifecycle",
                        "skill": "branch-lifecycle",
                        "makefile_target": 'make task-start TASK=<task-ref> OBJECTIVE="..."',
                        "description": "Manage task branch lifecycle.",
                        "execution_context": "Use for branch lifecycle.",
                        "argument_schema": [],
                        "loop": ["lifecycle"],
                    },
                    {
                        "command_id": "branch-review",
                        "skill": "branch-review",
                        "makefile_target": "make review-run",
                        "description": "Review a branch diff.",
                        "execution_context": "Use for branch review.",
                        "argument_schema": [],
                        "loop": ["review"],
                    },
                    {
                        "command_id": "planning-review",
                        "skill": "planning-review",
                        "makefile_target": "make plan-review DOC=<path>",
                        "description": "Review a planning doc.",
                        "execution_context": "Use for planning review.",
                        "argument_schema": [],
                        "loop": ["review"],
                    },
                ],
            }
        )
    )
    _write(
        repo / ".claude" / "commands" / "branch-lifecycle.md",
        'Active skill: `branch-lifecycle`\n\nMakefile entry point: `make task-start TASK=<task-ref> OBJECTIVE="..."`\n',
    )
    _write(
        repo / ".claude" / "commands" / "branch-review.md",
        "Active skill: `branch-review`\n\nMakefile entry point: `make review-run`\n",
    )
    _write(
        repo / ".claude" / "commands" / "planning-review.md",
        "Active skill: `planning-review`\n\nMakefile entry point: `make plan-review DOC=<path>`\n",
    )
    _write(
        repo / ".github" / "prompts" / "branch-lifecycle.prompt.md",
        'Load the `branch-lifecycle` skill for this workflow.\n\nMakefile entry point: `make task-start TASK=<task-ref> OBJECTIVE="..."`\n',
    )
    _write(
        repo / ".github" / "prompts" / "branch-review.prompt.md",
        "Load the `branch-review` skill for this workflow.\n\nMakefile entry point: `make review-run`\n",
    )
    _write(
        repo / ".github" / "prompts" / "planning-review.prompt.md",
        "Load the `planning-review` skill for this workflow.\n\nMakefile entry point: `make plan-review DOC=<path>`\n",
    )
    _write(
        repo / "docs" / "workstate" / "generated" / "codex-command-router.md",
        '- `/branch-lifecycle` (write) -> skill `branch-lifecycle` -> `make task-start TASK=<task-ref> OBJECTIVE="..."`\n'
        "- `/branch-review` (verify) -> skill `branch-review` -> `make review-run`\n"
        "- `/planning-review` (verify) -> skill `planning-review` -> `make plan-review DOC=<path>`\n",
    )
    return repo, manifest


def test_codex_resolution_matches_manifest(tmp_path: Path) -> None:
    repo, manifest = _make_repo(tmp_path)
    failures, backend = smoke_agent_workflows(repo, manifest, backend="codex")
    assert backend == "codex"
    assert failures == []


def test_claude_branch_lifecycle_resolution_matches_manifest(tmp_path: Path) -> None:
    repo, manifest = _make_repo(tmp_path)
    failures, backend = smoke_agent_workflows(repo, manifest, backend="claude", command_ids=["branch-lifecycle"])
    assert backend == "claude"
    assert failures == []


def test_copilot_resolution_mismatch_is_reported(tmp_path: Path) -> None:
    repo, manifest = _make_repo(tmp_path)
    _write(
        repo / ".github" / "prompts" / "planning-review.prompt.md",
        "Load the `planning-review` skill for this workflow.\n\nMakefile entry point: `make wrong-target`\n",
    )
    failures, backend = smoke_agent_workflows(repo, manifest, backend="copilot")
    assert backend == "copilot"
    assert len(failures) == 1
    assert "expected skill='planning-review', target='make plan-review DOC=<path>'" in failures[0]


def test_auto_backend_skips_when_environment_is_unknown(tmp_path: Path) -> None:
    repo, manifest = _make_repo(tmp_path)
    failures, backend = smoke_agent_workflows(repo, manifest, backend="auto", env={})
    assert backend is None
    assert failures == []