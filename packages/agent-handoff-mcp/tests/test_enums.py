from __future__ import annotations

from agent_handoff_mcp import build_write_actor
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.enums import (
    ActionStatus,
    BlockerStatus,
    FindingSeverity,
    FindingStatus,
    HandoffStatus,
    LaneMessageDirection,
    LaneStatus,
    MessageStatus,
    PlanCursorState,
    ReportStatus,
    ReviewMode,
    WorkerEventName,
)


def _enum_values(enum_cls: type) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def test_enum_values_match_core_validation_sets() -> None:
    assert handoff_core.HANDOFF_ACTIVE_STATUSES == frozenset(_enum_values(HandoffStatus))
    assert handoff_core.BLOCKER_STATUSES == frozenset(_enum_values(BlockerStatus))
    assert handoff_core.ACTION_STATUSES == frozenset(_enum_values(ActionStatus))
    assert handoff_core.REVIEW_FINDING_STATUSES == frozenset(_enum_values(FindingStatus))
    assert handoff_core.REVIEW_FINDING_SEVERITIES == frozenset(_enum_values(FindingSeverity))
    assert handoff_core.REVIEW_MODES == frozenset(_enum_values(ReviewMode))
    assert handoff_core.LANE_STATUSES == frozenset(_enum_values(LaneStatus))
    assert handoff_core.REPORT_STATUSES == frozenset(_enum_values(ReportStatus))
    assert handoff_core.MESSAGE_STATUSES == frozenset(_enum_values(MessageStatus))
    assert handoff_core.LANE_MESSAGE_DIRECTIONS == frozenset(_enum_values(LaneMessageDirection))
    assert handoff_core.PLAN_CURSOR_STATES == frozenset(_enum_values(PlanCursorState))


def test_enum_values_match_handoff_schema_constraints() -> None:
    schema = handoff_core.HANDOFF_SCHEMA_SQL

    for value in _enum_values(HandoffStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(BlockerStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(ActionStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(FindingStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(FindingSeverity):
        assert f"'{value}'" in schema
    for value in _enum_values(ReviewMode):
        assert f"'{value}'" in schema
    for value in _enum_values(LaneStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(ReportStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(MessageStatus):
        assert f"'{value}'" in schema
    for value in _enum_values(LaneMessageDirection):
        assert f"'{value}'" in schema
    for value in _enum_values(PlanCursorState):
        assert f"'{value}'" in schema


def test_build_write_actor_normalizes_and_filters_empty_values() -> None:
    actor = build_write_actor(
        agent=" codex ",
        branch=" tooling/review-hardening ",
        commit_sha=" abc123 ",
        lane_id=" backend-domain ",
    )

    assert actor == {
        "agent": "codex",
        "branch": "tooling/review-hardening",
        "commit_sha": "abc123",
        "lane_id": "backend-domain",
    }


def test_build_write_actor_returns_empty_dict_for_blank_inputs() -> None:
    assert build_write_actor(agent=" ", branch=None, commit_sha="", lane_id="\n") == {}


def test_worker_event_names_include_runtime_log_vocabulary() -> None:
    assert WorkerEventName.CYCLE_START == "cycle_start"
    assert WorkerEventName.EXEC_COMPLETE == "exec_complete"
    assert WorkerEventName.REVIEW_COMPLETE == "review_complete"
    assert WorkerEventName.CONTEXT_PRESSURE == "context_pressure"
