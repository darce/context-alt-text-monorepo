"""E17-9 Slice 2: /auto-fix bounded-loop skill scaffold invariants.

These tests pin the repository state that the `/auto-fix` skill depends
on. They do not drive the loop at runtime — per-iteration behavior
(commit-before-test, exit on first passed=true, single post-loop
`handoff_close_check`) is verified by integration tests that live
outside this scaffold. This file locks in the static surface:

1. ``portable_commands.json`` exposes ``/auto-fix`` with the argument
   schema the E17-9 plan requires (``failing_test_cmd``,
   ``max_iterations``, ``scope_hint``) and no extra knobs.
2. ``.claude/skills/auto-fix/SKILL.md`` exists and covers the three
   mandatory blocks from the plan: Precondition (feature-branch
   check), Per-iteration (bounded reads + commit + test_result +
   exit on passed=true), and Finalization (slice_complete decision +
   update_task_status(done) + single post-loop handoff_close_check).
3. The skill explicitly forbids the documented anti-patterns:
   ``detail="full"`` mid-loop, 300-second cadence waits,
   uncommitted-workspace iterations, running on ``main``/``master``.
4. The skill names the exit signal as ``verified_tests`` /
   ``test_result`` with ``passed=true`` tied to HEAD — not
   ``handoff_close_check.ok`` (explicit design constraint in the
   plan).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "agent-workflows" / "portable_commands.json"
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "auto-fix" / "SKILL.md"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


@pytest.fixture(scope="module")
def auto_fix_command(manifest: dict) -> dict:
    for entry in manifest["commands"]:
        if entry["command_id"] == "auto-fix":
            return entry
    pytest.fail("auto-fix entry missing from portable_commands.json")


def test_auto_fix_registered_in_manifest(auto_fix_command: dict) -> None:
    assert auto_fix_command["skill"] == "auto-fix"
    description = auto_fix_command["description"].lower()
    assert "loop" in description or "auto" in description or "fix" in description


def test_auto_fix_argument_schema_matches_plan(auto_fix_command: dict) -> None:
    args = {arg["name"]: arg for arg in auto_fix_command["argument_schema"]}
    failing = args.get("failing-test-cmd") or args.get("failing_test_cmd")
    assert failing is not None, args
    assert failing["required"] is True, failing

    max_iter = args.get("max-iterations") or args.get("max_iterations")
    assert max_iter is not None, args
    assert max_iter["required"] is False, max_iter

    scope_hint = args.get("scope-hint") or args.get("scope_hint")
    assert scope_hint is not None, args
    assert scope_hint["required"] is False, scope_hint

    # No extra knobs beyond the three documented inputs.
    allowed = {
        "failing-test-cmd",
        "failing_test_cmd",
        "max-iterations",
        "max_iterations",
        "scope-hint",
        "scope_hint",
    }
    extras = set(args) - allowed
    assert not extras, f"unexpected auto-fix argument(s): {extras}"


def test_auto_fix_skill_exists() -> None:
    assert SKILL_PATH.is_file(), f"missing skill: {SKILL_PATH}"


def test_auto_fix_skill_declares_three_mandatory_blocks() -> None:
    content = SKILL_PATH.read_text()
    required_sections = (
        "Precondition",
        "Per iteration",
        "Finalization",
    )
    missing = [marker for marker in required_sections if marker not in content]
    assert not missing, f"SKILL.md missing mandatory blocks: {missing}"


def test_auto_fix_skill_precondition_refuses_main() -> None:
    content = SKILL_PATH.read_text()
    lowered = content.lower()
    # The precondition must name main/master/None as refuse cases.
    assert "main" in lowered and "master" in lowered, "Precondition must explicitly refuse main/master target_branch."
    assert "target_branch" in content, "Precondition must reference `target_branch` from get_handoff_state."


def test_auto_fix_skill_names_per_iteration_exit_signal() -> None:
    content = SKILL_PATH.read_text()
    # Exit signal is a fresh passing test_result tied to HEAD, not handoff_close_check.ok.
    assert "passed=true" in content or "passed == true" in content or "passed = true" in content, (
        "Per-iteration exit signal must be documented as passed=true."
    )
    assert "test_result" in content or "verified_tests" in content, (
        "Exit signal must reference test_result/verified_tests."
    )


def test_auto_fix_skill_finalization_has_single_close_check() -> None:
    content = SKILL_PATH.read_text()
    assert "handoff_close_check" in content, "Finalization must call handoff_close_check exactly once post-loop."
    assert "require_fresh_tests" in content, "handoff_close_check must be invoked with require_fresh_tests=True."
    assert "slice_complete" in content, "Finalization must record a canonical slice_complete decision."
    assert "update_task_status" in content, "Finalization must set task status to done before the post-loop gate."


def test_auto_fix_skill_forbids_documented_anti_patterns() -> None:
    content = SKILL_PATH.read_text()
    lowered = content.lower()
    # detail="full" is explicitly forbidden mid-loop.
    assert 'detail="full"' in content or "detail='full'" in content or 'detail=\\"full\\"' in content, (
        'SKILL.md must explicitly call out detail="full" as the forbidden mid-loop read shape.'
    )
    # 300-second cadence is forbidden (Claude Code cache-miss trap).
    assert "300" in content, "SKILL.md must explicitly forbid 300-second ScheduleWakeup waits."
    # Uncommitted-workspace iterations are an anti-pattern.
    assert "commit" in lowered, "SKILL.md must describe commit-per-iteration discipline."


def test_auto_fix_skill_harness_scoped_cadence() -> None:
    content = SKILL_PATH.read_text()
    # Cadence rule is Claude-Code-only; Codex/Copilot iterate inline.
    assert "ScheduleWakeup" in content, "Cadence rule must name ScheduleWakeup (Claude Code primitive)."
    assert "Codex" in content and "Copilot" in content, "Cadence block must document Codex + Copilot inline iteration."
