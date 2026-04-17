from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "scripts" / "generate_agent_workflows.py"
CODEX_ROUTER_BEGIN = "<!-- BEGIN GENERATED: codex-command-router -->"
CODEX_ROUTER_END = "<!-- END GENERATED: codex-command-router -->"


def _run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _write_temp_manifest(tmp_path: Path, payload: dict[str, object]) -> Path:
    temp_repo = tmp_path / "repo"
    manifest = temp_repo / "config" / "agent-workflows" / "portable_commands.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload))

    instructions = temp_repo / "docs" / "agentic" / "instructions.md"
    instructions.parent.mkdir(parents=True, exist_ok=True)
    instructions.write_text(f"before\n{CODEX_ROUTER_BEGIN}\nplaceholder\n{CODEX_ROUTER_END}\nafter\n")

    claude_md = temp_repo / "CLAUDE.md"
    claude_md.write_text(f"before\n{CODEX_ROUTER_BEGIN}\nplaceholder\n{CODEX_ROUTER_END}\nafter\n")
    return manifest


def test_generate_agent_workflows_writes_expected_files(tmp_path: Path) -> None:
    manifest = _write_temp_manifest(
        tmp_path,
        {
            "version": 1,
            "commands": [
                {
                    "command_id": "branch-review",
                    "skill": "branch-review",
                    "makefile_target": "make review-run",
                    "description": "Review a branch diff.",
                    "execution_context": "Use for branch review.",
                    "argument_schema": [{"name": "scope", "required": False, "description": "Optional diff scope."}],
                    "loop": ["load diff", "record findings"],
                }
            ],
        },
    )
    temp_repo = manifest.parents[2]
    claude_out = temp_repo / ".claude" / "commands"
    prompts_out = temp_repo / ".github" / "prompts"

    proc = _run_generator(
        "--manifest",
        str(manifest),
        "--claude-out",
        str(claude_out),
        "--prompts-out",
        str(prompts_out),
    )
    assert proc.returncode == 0, proc.stderr

    claude_file = claude_out / "branch-review.md"
    prompt_file = prompts_out / "branch-review.prompt.md"
    assert claude_file.exists()
    assert prompt_file.exists()
    assert "Active skill: `branch-review`" in claude_file.read_text()
    assert "Load the `branch-review` skill" in prompt_file.read_text()


def test_generate_agent_workflows_check_detects_drift(tmp_path: Path) -> None:
    manifest = _write_temp_manifest(
        tmp_path,
        {
            "version": 1,
            "commands": [
                {
                    "command_id": "planning-review",
                    "skill": "planning-review",
                    "makefile_target": "make plan-review DOC=<path>",
                    "description": "Review a planning doc.",
                    "execution_context": "Use for planning review.",
                    "argument_schema": [{"name": "doc", "required": True, "description": "Planning document path."}],
                    "loop": ["load doc", "record findings"],
                }
            ],
        },
    )
    temp_repo = manifest.parents[2]
    claude_out = temp_repo / ".claude" / "commands"
    prompts_out = temp_repo / ".github" / "prompts"

    first = _run_generator(
        "--manifest",
        str(manifest),
        "--claude-out",
        str(claude_out),
        "--prompts-out",
        str(prompts_out),
    )
    assert first.returncode == 0, first.stderr

    target = claude_out / "planning-review.md"
    target.write_text(target.read_text() + "\nmanual drift\n")

    drift = _run_generator(
        "--manifest",
        str(manifest),
        "--claude-out",
        str(claude_out),
        "--prompts-out",
        str(prompts_out),
        "--check",
    )
    assert drift.returncode == 1
    assert "drift detected" in drift.stderr


def test_generate_agent_workflows_rejects_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "portable_commands.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "commands": [
                    {
                        "command_id": "bad",
                        "skill": "",
                        "makefile_target": "make something",
                        "description": "Broken entry.",
                        "execution_context": "Broken.",
                        "argument_schema": [],
                        "loop": ["one step"],
                    }
                ],
            }
        )
    )

    proc = _run_generator("--manifest", str(manifest), "--claude-out", str(tmp_path / "claude"))
    assert proc.returncode == 1
    assert "skill must be a non-empty string" in proc.stderr
