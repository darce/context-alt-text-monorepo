"""E17-9 Slice 2: /auto-fix static guards plus bounded-loop runtime proof.

These tests still pin the generated command and skill contract, but they now
also execute a hermetic auto-fix loop over the handoff APIs so the proof is no
longer scaffold-only.

What this file locks in:

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
4. The runtime helper proves the operational contract: precondition
   failures record no loop writes, each iteration records a test row on its
   candidate commit SHA, the loop exits on the first passing HEAD row, the
   post-loop close check runs exactly once, and exhaustion records a blocker
   without fabricating a slice-complete decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "config" / "agent-workflows" / "portable_commands.json"
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "auto-fix" / "SKILL.md"
BASELINE_PATH = REPO_ROOT / "packages" / "agent-orchestrator-mcp" / "tests" / "fixtures" / "review_baseline.json"


def _parse(raw: str | dict) -> dict:
    result = raw if isinstance(raw, dict) else json.loads(raw)
    if isinstance(result, dict) and result.get("schema_version") == 2:
        data = result.get("data", {})
        scope = result.get("scope", {})
        flat = {**result, **data}
        if "task_ref" not in flat and scope.get("task_ref"):
            flat["task_ref"] = scope["task_ref"]
        return flat
    return result


def _structured_slice_rationale(label: str) -> str:
    return (
        "## Changes\n"
        f"- close {label} through the bounded auto-fix loop.\n\n"
        "## Verification\n"
        "- simulated auto-fix loop contract test.\n\n"
        "## Schema / Contract Changes\n"
        "- none.\n\n"
        "## Open Threads\n"
        "- none."
    )


def _identity_payload_bytes(task_ref: str) -> int:
    from agent_handoff_mcp import get_handoff_state

    response = get_handoff_state(task_ref=task_ref, sections="identity")
    data = response["data"] if isinstance(response, dict) and "data" in response else response
    return len(json.dumps(data, sort_keys=True).encode("utf-8"))


def _count_rows(table: str, task_ref: str) -> int:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    with _get_db_connection() as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE task_ref = ?", (task_ref,)).fetchone()[0])


def _count_slice_complete_decisions(task_ref: str) -> int:
    from agent_handoff_mcp.shared_schema import _get_db_connection

    with _get_db_connection() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE task_ref = ? AND decision LIKE ?",
                (task_ref, "%slice_complete%"),
            ).fetchone()[0]
        )


def _run_auto_fix_contract(
    *,
    task_ref: str,
    failing_test_cmd: str,
    iteration_outcomes: list[bool],
    max_iterations: int,
    record_slice_complete: bool = True,
) -> dict:
    from agent_handoff_mcp import (
        generate_current_task_md,
        get_handoff_state,
        get_verified_tests,
        handoff_close_check,
        record_decision,
        record_test_result,
        report_blocker,
        update_task_status,
    )

    initial_identity = get_handoff_state(task_ref=task_ref, sections="identity")
    initial_data = initial_identity["data"] if isinstance(initial_identity, dict) else initial_identity
    active = initial_data["active"]
    target_branch = active.get("target_branch") if isinstance(active, dict) else None

    result: dict[str, object] = {
        "ok": False,
        "iterations_run": 0,
        "identity_bytes": [],
        "close_check_calls": 0,
        "winning_commit_sha": None,
        "close_check": None,
        "error": None,
    }

    if target_branch in {None, "main", "master"}:
        result["error"] = (
            "auto-fix requires an active task with a feature `target_branch`; "
            "run `make task-start TASK=<id>` first."
        )
        return result

    _parse(
        record_decision(
            session=f"{task_ref}-auto-fix-open",
            decision=f"cdx_auto_fix_open_{task_ref.lower().replace('-', '_')}_loop",
            rationale="Open bounded auto-fix loop for runtime contract proof.",
            task_ref=task_ref,
            actor={"agent": "test-agent", "branch": target_branch, "commit_sha": "open001"},
        )
    )

    winning_commit_sha: str | None = None
    for iteration, passed in enumerate(iteration_outcomes[:max_iterations], start=1):
        identity_bytes = _identity_payload_bytes(task_ref)
        result["identity_bytes"].append(identity_bytes)

        commit_sha = f"fix{iteration:03d}"
        _parse(
            record_test_result(
                session=f"{task_ref}-iter-{iteration}",
                command=failing_test_cmd,
                passed=passed,
                result=f"iteration {iteration} {'passed' if passed else 'failed'}",
                task_ref=task_ref,
                actor={"agent": "test-agent", "branch": target_branch, "commit_sha": commit_sha},
            )
        )
        result["iterations_run"] = iteration

        passed_rows = _parse(
            get_verified_tests(task_ref=task_ref, commit_sha=commit_sha, passed=True, limit=5)
        )
        if passed_rows["returned"] >= 1:
            winning_commit_sha = commit_sha
            result["winning_commit_sha"] = commit_sha
            break

    if winning_commit_sha is None:
        blocker = _parse(
            report_blocker(
                operation="add",
                description=f"auto-fix exhausted {max_iterations} iterations without convergence",
                task_ref=task_ref,
                actor={
                    "agent": "test-agent",
                    "branch": target_branch,
                    "commit_sha": f"fix{result['iterations_run']:03d}",
                },
            )
        )
        result["blocker"] = blocker
        return result

    if record_slice_complete:
        _parse(
            record_decision(
                session=f"{task_ref}-auto-fix-close",
                decision=f"cdx_slice_complete_{task_ref.lower().replace('-', '_')}_autofix",
                rationale=_structured_slice_rationale(task_ref),
                task_ref=task_ref,
                actor={"agent": "test-agent", "branch": target_branch, "commit_sha": winning_commit_sha},
            )
        )

    latest_identity = get_handoff_state(task_ref=task_ref, sections="identity")
    latest_data = latest_identity["data"] if isinstance(latest_identity, dict) else latest_identity
    active = latest_data["active"]
    revision = int(active["revision"])
    _parse(
        update_task_status(
            task_ref=task_ref,
            status="done",
            expected_revision=revision,
            actor={"agent": "test-agent", "branch": target_branch, "commit_sha": winning_commit_sha},
        )
    )
    _parse(generate_current_task_md(task_ref=task_ref, write_file=True))

    result["close_check_calls"] = 1
    result["close_check"] = _parse(
        handoff_close_check(
            task_ref=task_ref,
            enforce=True,
            require_fresh_tests=True,
            current_commit_sha=winning_commit_sha,
        )
    )
    result["ok"] = bool(result["close_check"]["ok"])
    return result


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


@pytest.fixture(scope="module")
def auto_fix_command(manifest: dict) -> dict:
    for entry in manifest["commands"]:
        if entry["command_id"] == "auto-fix":
            return entry
    pytest.fail("auto-fix entry missing from portable_commands.json")


@pytest.fixture()
def isolated_handoff(tmp_path: Path) -> dict:
    from agent_handoff_mcp import RuntimeConfig, configure_runtime

    state_dir = tmp_path / ".task-state"
    current_task_path = tmp_path / "CURRENT_TASK.json"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir, current_task_path=current_task_path)
    configure_runtime(runtime)
    return {
        "state_dir": state_dir,
        "current_task_path": current_task_path,
    }


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
    assert "main" in lowered and "master" in lowered, "Precondition must explicitly refuse main/master target_branch."
    assert "target_branch" in content, "Precondition must reference `target_branch` from get_handoff_state."


def test_auto_fix_skill_names_per_iteration_exit_signal() -> None:
    content = SKILL_PATH.read_text()
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
    assert 'detail="full"' in content or "detail='full'" in content or 'detail=\\"full\\"' in content, (
        'SKILL.md must explicitly call out detail="full" as the forbidden mid-loop read shape.'
    )
    assert "300" in content, "SKILL.md must explicitly forbid 300-second ScheduleWakeup waits."
    assert "commit" in lowered, "SKILL.md must describe commit-per-iteration discipline."


def test_auto_fix_skill_harness_scoped_cadence() -> None:
    content = SKILL_PATH.read_text()
    assert "ScheduleWakeup" in content, "Cadence rule must name ScheduleWakeup (Claude Code primitive)."
    assert "Codex" in content and "Copilot" in content, "Cadence block must document Codex + Copilot inline iteration."


def test_auto_fix_runtime_loop_exits_on_first_passing_head_row(isolated_handoff: dict) -> None:
    from agent_handoff_mcp import get_verified_tests, set_handoff_state

    _parse(
        set_handoff_state(
            task_ref="AUTOFIX-CONTRACT",
            objective="Exercise bounded auto-fix loop contract",
            status="in_progress",
            target_branch="feature/autofix-contract",
        )
    )
    runtime = _run_auto_fix_contract(
        task_ref="AUTOFIX-CONTRACT",
        failing_test_cmd="pytest tests/test_fixture.py -q",
        iteration_outcomes=[False, False, True, True],
        max_iterations=5,
    )

    assert runtime["ok"] is True, runtime
    assert runtime["iterations_run"] == 3
    assert runtime["winning_commit_sha"] == "fix003"
    assert runtime["close_check_calls"] == 1
    assert runtime["close_check"]["ready_to_close"] is True

    passed_rows = _parse(get_verified_tests(task_ref="AUTOFIX-CONTRACT", passed=True, limit=10))
    assert passed_rows["returned"] == 1
    assert passed_rows["tests"][0]["commit_sha"] == "fix003"

    baseline = json.loads(BASELINE_PATH.read_text())
    ceiling = int(baseline["identity_response_bytes"] * 1.10)
    assert all(identity_bytes <= ceiling for identity_bytes in runtime["identity_bytes"]), runtime["identity_bytes"]


def test_auto_fix_runtime_close_check_fails_without_slice_complete_decision(isolated_handoff: dict) -> None:
    from agent_handoff_mcp import set_handoff_state

    _parse(
        set_handoff_state(
            task_ref="AUTOFIX-NO-SLICE",
            objective="Prove close-check stays red without slice-complete",
            status="in_progress",
            target_branch="feature/autofix-no-slice",
        )
    )
    runtime = _run_auto_fix_contract(
        task_ref="AUTOFIX-NO-SLICE",
        failing_test_cmd="pytest tests/test_fixture.py -q",
        iteration_outcomes=[False, True],
        max_iterations=3,
        record_slice_complete=False,
    )

    assert runtime["ok"] is False
    assert runtime["close_check_calls"] == 1
    close_check = runtime["close_check"]
    assert close_check["ready_to_close"] is False
    assert close_check["checks"]["current_commit_handoff"]["is_violation"] is True
    assert _count_slice_complete_decisions("AUTOFIX-NO-SLICE") == 0


def test_auto_fix_runtime_precondition_rejects_main_branch_without_writes(isolated_handoff: dict) -> None:
    from agent_handoff_mcp import set_handoff_state

    task_ref = "AUTOFIX-MAIN"
    _parse(
        set_handoff_state(
            task_ref=task_ref,
            objective="Reject main-branch auto-fix precondition",
            status="in_progress",
            target_branch="main",
        )
    )
    before = {
        "decisions": _count_rows("decisions", task_ref),
        "verified_tests": _count_rows("verified_tests", task_ref),
        "blockers": _count_rows("blockers", task_ref),
    }

    runtime = _run_auto_fix_contract(
        task_ref=task_ref,
        failing_test_cmd="pytest tests/test_fixture.py -q",
        iteration_outcomes=[True],
        max_iterations=1,
    )

    after = {
        "decisions": _count_rows("decisions", task_ref),
        "verified_tests": _count_rows("verified_tests", task_ref),
        "blockers": _count_rows("blockers", task_ref),
    }
    assert runtime["ok"] is False
    assert "feature `target_branch`" in str(runtime["error"])
    assert before == after


def test_auto_fix_runtime_exhaustion_records_blocker_without_close_check(isolated_handoff: dict) -> None:
    from agent_handoff_mcp import get_handoff_state, set_handoff_state

    task_ref = "AUTOFIX-EXHAUSTED"
    _parse(
        set_handoff_state(
            task_ref=task_ref,
            objective="Record blocker on bounded-loop exhaustion",
            status="in_progress",
            target_branch="feature/autofix-exhausted",
        )
    )
    runtime = _run_auto_fix_contract(
        task_ref=task_ref,
        failing_test_cmd="pytest tests/test_fixture.py -q",
        iteration_outcomes=[False, False],
        max_iterations=2,
    )

    assert runtime["ok"] is False
    assert runtime["iterations_run"] == 2
    assert runtime["close_check_calls"] == 0
    assert runtime["winning_commit_sha"] is None
    assert runtime["blocker"]["ok"] is True
    assert _count_rows("blockers", task_ref) == 1
    assert _count_slice_complete_decisions(task_ref) == 0

    identity = get_handoff_state(task_ref=task_ref, sections="identity")
    active = identity["data"]["active"] if isinstance(identity, dict) else identity["active"]
    assert active["status"] == "in_progress"
