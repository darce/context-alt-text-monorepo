from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


@pytest.fixture()
def isolated_env(tmp_path: Path) -> dict:
    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
    mcp_server.configure_runtime(runtime)
    handoff_core.set_handoff_state(
        task_ref="verified-tests-task",
        objective="Verified tests query coverage",
        status="in_progress",
    )
    return {"state_dir": state_dir, "task_ref": "verified-tests-task"}


def _parse(payload: str | dict) -> dict:
    raw = json.loads(payload) if isinstance(payload, str) else payload
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        return {**raw, **raw.get("data", {})}
    return raw


def test_get_verified_tests_returns_descending_rows(isolated_env: dict) -> None:
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_one.py -q",
        passed=True,
        result="1 passed in 0.01s",
        exit_code=0,
        actor={"lane_id": "lane-a", "branch": "feature/tests", "commit_sha": "abc1234"},
    )
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_two.py -q",
        passed=False,
        result="1 failed in 0.02s",
        exit_code=1,
        actor={"lane_id": "lane-b", "branch": "feature/tests", "commit_sha": "def5678"},
    )

    result = _parse(handoff_core.get_verified_tests())

    assert result["ok"] is True
    assert result["returned"] == 2
    assert [row["command"] for row in result["tests"]] == [
        "pytest tests/test_two.py -q",
        "pytest tests/test_one.py -q",
    ]


def test_get_verified_tests_defaults_to_active_task_scope(isolated_env: dict) -> None:
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_active_scope.py -q",
        passed=True,
        result="2 passed in 0.02s",
        exit_code=0,
        task_ref="verified-tests-task",
    )
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_other_scope.py -q",
        passed=True,
        result="2 passed in 0.02s",
        exit_code=0,
        task_ref="other-task",
    )

    result = _parse(handoff_core.get_verified_tests())

    assert result["ok"] is True
    assert result["tests"]
    assert {row["task_ref"] for row in result["tests"]} == {"verified-tests-task"}


def test_get_verified_tests_filters_by_passed_and_lane(isolated_env: dict) -> None:
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_lane_a.py -q",
        passed=True,
        result="2 passed in 0.02s",
        exit_code=0,
        actor={"lane_id": "lane-a", "branch": "feature/tests", "commit_sha": "aaa1111"},
    )
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_lane_b.py -q",
        passed=False,
        result="1 failed in 0.03s",
        exit_code=1,
        actor={"lane_id": "lane-b", "branch": "feature/tests", "commit_sha": "bbb2222"},
    )

    result = _parse(handoff_core.get_verified_tests(passed=True, lane_id="lane-a"))

    assert result["ok"] is True
    assert result["returned"] == 1
    assert result["tests"][0]["lane_id"] == "lane-a"
    assert result["tests"][0]["passed"] is True


def test_get_verified_tests_filters_by_branch_and_commit(isolated_env: dict) -> None:
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_branch_match.py -q",
        passed=True,
        result="4 passed in 0.04s",
        exit_code=0,
        actor={"lane_id": "lane-a", "branch": "feature/branch-a", "commit_sha": "sha-match"},
    )
    handoff_core.record_test_result(
        session="s1",
        command="pytest tests/test_branch_other.py -q",
        passed=True,
        result="4 passed in 0.05s",
        exit_code=0,
        actor={"lane_id": "lane-a", "branch": "feature/branch-b", "commit_sha": "sha-other"},
    )

    result = _parse(handoff_core.get_verified_tests(branch="feature/branch-a", commit_sha="sha-match"))

    assert result["ok"] is True
    assert result["returned"] == 1
    assert result["tests"][0]["branch"] == "feature/branch-a"
    assert result["tests"][0]["commit_sha"] == "sha-match"


def test_get_verified_tests_honors_limit_and_offset(isolated_env: dict) -> None:
    for index in range(3):
        handoff_core.record_test_result(
            session="s1",
            command=f"pytest tests/test_{index}.py -q",
            passed=True,
            result=f"{index + 1} passed in 0.0{index + 1}s",
            exit_code=0,
        )

    result = _parse(handoff_core.get_verified_tests(limit=1, offset=1))

    assert result["ok"] is True
    assert result["returned"] == 1
    assert result["total_matching"] == 3
    assert result["has_more"] is True
