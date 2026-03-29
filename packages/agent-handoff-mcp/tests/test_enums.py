from __future__ import annotations

import re
from pathlib import Path

from agent_handoff_mcp import (
    ReviewFindingDetails,
    ReviewKind,
    ReviewScopeSource,
    SliceReviewPacket,
    WriteActor,
    build_write_actor,
)
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
    normalize_model_identity,
    normalize_model_label,
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
    assert handoff_core.REVIEW_KINDS == frozenset(_enum_values(ReviewKind))
    assert handoff_core.REVIEW_SCOPE_SOURCES == frozenset(_enum_values(ReviewScopeSource))
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


def test_build_write_actor_derives_unified_model_identity_from_model_fields() -> None:
    actor = build_write_actor(
        model=" claude-opus-4-0520 ",
        reasoning_level=" High ",
        branch=" feature/model-identity ",
    )

    assert actor == {
        "agent": "Opus 4.6 high",
        "model": "claude-opus-4-0520",
        "model_label": "Opus 4.6",
        "reasoning_level": "high",
        "branch": "feature/model-identity",
    }


def test_build_write_actor_keeps_unknown_models_human_readable() -> None:
    actor = build_write_actor(model="custom-model-preview", reasoning_level="medium")

    assert actor["agent"] == "custom-model-preview medium"
    assert actor["model_label"] == "custom-model-preview"


def test_build_write_actor_returns_empty_dict_for_blank_inputs() -> None:
    assert build_write_actor(agent=" ", branch=None, commit_sha="", lane_id="\n") == {}


def test_model_identity_helpers_normalize_known_labels_and_skip_inherit() -> None:
    assert normalize_model_label("claude-sonnet-4-20250514") == "Sonnet 4"
    assert normalize_model_label("unknown-model") == "unknown-model"
    assert normalize_model_identity("Opus 4.6", "inherit") == "Opus 4.6"


def test_public_review_packet_types_are_importable_from_package_root() -> None:
    assert ReviewFindingDetails.__name__ == "ReviewFindingDetails"
    assert WriteActor.__name__ == "WriteActor"
    assert SliceReviewPacket.__name__ == "SliceReviewPacket"
    assert ReviewKind.PLANNING == "planning"
    assert ReviewScopeSource.SLICE_PACKET == "slice_packet"


def test_worker_event_names_include_runtime_log_vocabulary() -> None:
    runtime_sources = (
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "worker_daemon.py",
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "adapters" / "codex_cli.py",
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "adapters" / "claude_code.py",
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "adapters" / "codex_subagent.py",
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "adapters" / "local_model.py",
    )
    joined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_sources)

    for member in WorkerEventName:
        assert f"WorkerEventName.{member.name}" in joined


def test_runtime_event_strings_are_backed_by_worker_event_enum() -> None:
    runtime_sources = (
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "worker_daemon.py",
        Path(handoff_core.__file__).resolve().parent / "orchestration" / "ace_metrics.py",
    )
    allowed_values = {member.value for member in WorkerEventName}
    observed_values: set[str] = set()

    for path in runtime_sources:
        text = path.read_text(encoding="utf-8")
        observed_values.update(re.findall(r'if\s+event\s*==\s*"([^"]+)"', text))
        observed_values.update(re.findall(r'e\.get\("event"\)\s*==\s*"([^"]+)"', text))
        observed_values.update(re.findall(r'"INFO",\s*"([^"]+)"', text))
        observed_values.update(re.findall(r'"WARNING",\s*"([^"]+)"', text))
        observed_values.update(re.findall(r'"ERROR",\s*"([^"]+)"', text))

    observed_values.discard("event")
    assert observed_values <= allowed_values
