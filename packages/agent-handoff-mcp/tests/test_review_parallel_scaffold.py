"""E17-9 Slice 1: /review-parallel scaffold invariants.

These tests pin the repository state that the `/review-parallel` skill
depends on. They do not measure runtime token cost — that sits on top
of the baseline fixture and will be asserted by a follow-up slice that
records real ``turn_metrics`` rows.

What this file locks in:

1. ``portable_commands.json`` exposes ``/review-parallel`` with the
   argument schema the E17-9 plan requires — ``reviewers_count`` and
   ``reviewer_prompt_template`` only, and explicitly NO ``merge_strategy``
   knob (resolved planning finding E17-9-PLAN-09).
2. ``.claude/skills/review-parallel/SKILL.md`` exists and carries the
   harness-routing table rows the plan requires (Claude Code / Codex /
   Copilot / external orchestrator) plus the explicit prohibition on
   calling ``ClaudeCodeAdapter`` from inside an active Claude Code
   coordinator session (resolved planning finding E17-9-PLAN-05).
3. Reviewer prompt templates live at the harness-neutral path
   ``config/agent-workflows/prompts/review-parallel/`` so the Claude,
   VS Code, and Codex adapters all resolve them (resolved planning
   finding E17-9-PLAN-10).
4. The Slice 1 baseline fixture
   ``packages/agent-orchestrator-mcp/tests/fixtures/review_baseline.json``
   exists and declares the schema the token-envelope assertion will
   consume (resolved planning finding E17-9-PLAN-11).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "agent-workflows" / "portable_commands.json"
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "review-parallel" / "SKILL.md"
PROMPT_DIR = REPO_ROOT / "config" / "agent-workflows" / "prompts" / "review-parallel"
BASELINE_PATH = (
    REPO_ROOT
    / "packages"
    / "agent-orchestrator-mcp"
    / "tests"
    / "fixtures"
    / "review_baseline.json"
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


@pytest.fixture(scope="module")
def review_parallel_command(manifest: dict) -> dict:
    for entry in manifest["commands"]:
        if entry["command_id"] == "review-parallel":
            return entry
    pytest.fail("review-parallel entry missing from portable_commands.json")


def test_review_parallel_registered_in_manifest(review_parallel_command: dict) -> None:
    assert review_parallel_command["skill"] == "review-parallel"
    assert "review_findings" in review_parallel_command["description"].lower() or (
        "parallel" in review_parallel_command["description"].lower()
    )


def test_review_parallel_argument_schema_matches_plan(review_parallel_command: dict) -> None:
    names = {arg["name"] for arg in review_parallel_command["argument_schema"]}
    assert "reviewers-count" in names or "reviewers_count" in names, names
    assert "reviewer-prompt-template" in names or "reviewer_prompt_template" in names, names
    assert "merge-strategy" not in names and "merge_strategy" not in names, (
        "merge_strategy must not be re-introduced — see E17-9-PLAN-09. "
        "`review_findings(operation='merge')` is an unconditional union."
    )


def test_review_parallel_skill_exists() -> None:
    assert SKILL_PATH.is_file(), f"missing skill: {SKILL_PATH}"


def test_review_parallel_skill_declares_harness_routing() -> None:
    content = SKILL_PATH.read_text()
    required_markers = (
        "Claude Code",
        "Codex",
        "Copilot",
        "Agent` tool",
        "run_structured_turn",
        "BackendAdapter",
    )
    missing = [marker for marker in required_markers if marker not in content]
    assert not missing, f"SKILL.md missing required harness-routing markers: {missing}"


def test_review_parallel_skill_forbids_claude_cli_inside_claude_coordinator() -> None:
    content = SKILL_PATH.read_text()
    assert "ClaudeCodeAdapter" in content, (
        "SKILL.md must mention ClaudeCodeAdapter when documenting the forbidden "
        "CLI-subprocess path — see E17-9-PLAN-05."
    )
    lowered = content.lower()
    assert "forbid" in lowered or "must not" in lowered or "do not" in lowered, (
        "SKILL.md must explicitly forbid invoking the claude CLI adapter from "
        "inside an active Claude Code coordinator session."
    )


def test_reviewer_prompt_template_directory_exists() -> None:
    assert PROMPT_DIR.is_dir(), f"missing harness-neutral prompt dir: {PROMPT_DIR}"
    markdown_templates = sorted(PROMPT_DIR.glob("*.md"))
    assert markdown_templates, f"no reviewer prompt templates under {PROMPT_DIR}"


def test_baseline_fixture_declares_expected_schema() -> None:
    assert BASELINE_PATH.is_file(), f"missing baseline fixture: {BASELINE_PATH}"
    payload = json.loads(BASELINE_PATH.read_text())
    required_keys = {
        "schema_version",
        "captured_at",
        "captured_by",
        "fixture_diff_lines",
        "serial_branch_review_total_tokens",
        "identity_response_bytes",
        "measurement_method",
    }
    missing = required_keys - set(payload)
    assert not missing, f"baseline fixture missing required keys: {missing}"
    assert payload["schema_version"] == 1, payload["schema_version"]
    assert isinstance(payload["measurement_method"], str)
    assert payload["fixture_diff_lines"] >= 1
