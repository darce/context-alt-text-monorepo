from __future__ import annotations

from enum import StrEnum


class HandoffStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    DONE = "done"


class BlockerStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ActionStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


class FindingStatus(StrEnum):
    OPEN = "open"
    FIXED = "fixed"
    WONTFIX = "wontfix"
    DEFERRED = "deferred"


class FindingSeverity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewMode(StrEnum):
    BRANCH = "branch"
    RELEASE_AUDIT = "release_audit"


class LaneStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    BLOCKED = "blocked"
    REVIEW = "review"
    MERGED = "merged"
    CLOSED = "closed"


class ReportStatus(StrEnum):
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    SUPERSEDED = "superseded"


class MessageStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"


class LaneMessageDirection(StrEnum):
    ORCHESTRATOR_TO_WORKER = "orchestrator_to_worker"
    WORKER_TO_ORCHESTRATOR = "worker_to_orchestrator"


class PlanCursorState(StrEnum):
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ESCALATED = "escalated"


class WorkerEventName(StrEnum):
    DAEMON_START = "daemon_start"
    DAEMON_STOP = "daemon_stop"
    HANDOFF_SUBPROCESS_FAILED = "handoff_subprocess_failed"
    HANDOFF_RETRY_START = "handoff_retry_start"
    HANDOFF_RETRY_COMPLETE = "handoff_retry_complete"
    HANDOFF_RETRY_FAILED = "handoff_retry_failed"
    DORMANT_ENTERED = "dormant_entered"
    DORMANT_EXITED = "dormant_exited"
    POLL_ERROR = "poll_error"
    MCP_BACKEND_OVERRIDE = "mcp_backend_override"
    MCP_MODEL_OVERRIDE = "mcp_model_override"
    MCP_EFFORT_OVERRIDE = "mcp_effort_override"
    CYCLE_START = "cycle_start"
    FIX_PROMPT_FAILED = "fix_prompt_failed"
    REASONING_EFFORT_SELECTED = "reasoning_effort_selected"
    EXEC_SPAWNED = "exec_spawned"
    EXEC_HEARTBEAT = "exec_heartbeat"
    SUBAGENT_TURN_COMPLETE = "subagent_turn_complete"
    EXEC_START = "exec_start"
    EXEC_FAILED = "exec_failed"
    EXEC_COMPLETE = "exec_complete"
    ARTIFACT_INDEXED = "artifact_indexed"
    CONTEXT_PRESSURE = "context_pressure"
    NEEDS_GUIDANCE = "needs_guidance"
    HANDOFF_FAILED = "handoff_failed"
    SCOPE_VIOLATION = "scope_violation"
    REVIEW_START = "review_start"
    REVIEW_FAILED = "review_failed"
    REVIEW_COMPLETE = "review_complete"
    ACE_REFLECT_ERROR = "ace_reflect_error"
    FINDING_DIFF = "finding_diff"
    VERIFICATION_START = "verification_start"
    VERIFICATION_COMPLETE = "verification_complete"
    FIX_CYCLE_NEEDED = "fix_cycle_needed"
    REVIEW_EXHAUSTED = "review_exhausted"
    EXHAUSTION_STREAK = "exhaustion_streak"
    LANE_EXHAUSTION_FORCED_STOP = "lane_exhaustion_forced_stop"
    POLL_SLEEP = "poll_sleep"
