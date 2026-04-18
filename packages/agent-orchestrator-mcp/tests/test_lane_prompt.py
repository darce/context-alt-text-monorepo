from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from agent_orchestrator_mcp.orchestration.handoff_read_shapes import global_context_kwargs

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
SCRIPT_PATH = ORCHESTRATION_DIR / "lane_prompt.py"


def _load_lane_prompt_module():
    spec = importlib.util.spec_from_file_location("lane_prompt", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load lane_prompt module from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_require_dict = module._require_dict_payload

    def _compat_require_dict(payload, *, source: str):
        if isinstance(payload, str):
            payload = json.loads(payload)
        return original_require_dict(payload, source=source)

    module._require_dict_payload = _compat_require_dict
    return module


def test_build_prompt_returns_no_work_message_when_lane_is_idle() -> None:
    module = _load_lane_prompt_module()

    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )

    assert prompt == module.NO_WORK_MESSAGE


def test_build_prompt_includes_messages_actions_and_findings() -> None:
    module = _load_lane_prompt_module()

    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Phase 5 backend-domain slice."},
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                },
                {
                    "id": 9,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "brief:api-contract-changed",
                    "message": "Contract brief for downstream work.",
                },
            ],
            "actions": [
                {
                    "id": 72,
                    "status": "pending",
                    "priority": 1,
                    "action": "Implement the backend-domain slice.",
                }
            ],
            "blockers": [],
            "findings": [
                {
                    "finding_id": "P5-IMPL-01",
                    "status": "open",
                    "severity": "medium",
                    "file_path": "docs/tasks/phase5.md",
                    "line_start": 411,
                    "description": "Checklist item is still unchecked.",
                }
            ],
            "reports": [{"status": "submitted", "summary": "backend-domain lane ready for orchestrator review."}],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )

    assert "Assignment Inbox:" in prompt
    assert "Context Budget:" in prompt
    assert "Prompt Budget:" in prompt
    assert "Runtime Guidance:" in prompt
    assert "Dependency Briefs:" in prompt
    assert "Reporting Contract:" in prompt
    assert "Contract brief for downstream work." in prompt
    assert "Recent lane decisions/tests are omitted by default" in prompt
    assert "Verification commands for this lane:" in prompt
    assert "PYENV_VERSION=description-service" in prompt
    assert "Backend runtime notes:" in prompt
    assert "make lane-handoff" in prompt
    assert "Working directory:" in prompt
    assert "apps/prototype-description-service/" in prompt
    assert "Owned paths" in prompt
    assert "Constraints:" in prompt
    assert "Do not edit HTTP router files." in prompt
    assert "Assignment inbox contributes" in prompt
    assert "Recent lane history is omitted from the default prompt budget." in prompt


def test_build_prompt_formats_structured_briefs_compactly() -> None:
    module = _load_lane_prompt_module()

    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-frontend", "objective": "Frontend slice."},
            "messages": [
                {
                    "id": 9,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "brief:api-contract-changed",
                    "message": "Contract brief for downstream work.",
                    "payload": {
                        "source_lane": "backend-domain",
                        "reason": "api-contract-changed",
                        "summary": "Retention export contract now includes purge eligibility metadata.",
                        "required_actions": ["Update the typed client.", "Refresh the UI copy."],
                        "artifacts": ["apps/prototype-description-service/export_service.py"],
                    },
                }
            ],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        orchestrator_root=REPO_ROOT,
    )

    assert "from backend-domain" in prompt
    assert "Actions: Update the typed client.; Refresh the UI copy." in prompt
    assert "Artifacts: apps/prototype-description-service/export_service.py" in prompt


def test_build_prompt_bounds_assignment_items_for_focus() -> None:
    module = _load_lane_prompt_module()
    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [
                {
                    "id": idx,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": f"assignment-{idx}",
                    "message": "Work item.",
                }
                for idx in range(20)
            ],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )
    assert "additional item(s) omitted to keep the worker prompt focused" in prompt


def test_build_prompt_includes_recent_lane_history_only_when_requested() -> None:
    module = _load_lane_prompt_module()
    activity = {
        "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
        "messages": [
            {
                "id": 1,
                "direction": "orchestrator_to_worker",
                "status": "open",
                "subject": "assignment",
                "message": "Implement the lane slice.",
            }
        ],
        "actions": [],
        "blockers": [],
        "findings": [],
        "decisions": [
            {"id": 11, "decision": "Use the compact brief path."},
        ],
        "tests": [
            {"id": 22, "passed": 1, "command": "pytest recognition/tests/unit/test_export_service.py"},
        ],
        "reports": [],
    }

    default_prompt, _ = module._build_prompt(
        activity,
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )
    expanded_prompt, _ = module._build_prompt(
        activity,
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
        include_lane_history=True,
    )

    assert "Recent Lane History:" not in default_prompt
    assert "Recent Lane History:" in expanded_prompt
    assert "Use the compact brief path." in expanded_prompt
    assert "[pass] pytest recognition/tests/unit/test_export_service.py" in expanded_prompt
    assert "Escalated lane history is included below" in expanded_prompt


def test_build_prompt_includes_global_context_only_when_requested() -> None:
    module = _load_lane_prompt_module()
    calls: list[dict[str, object]] = []

    def fake_get_handoff_state(**kwargs: object) -> str:
        calls.append(dict(kwargs))
        return json.dumps(
            {
                "ok": True,
                "actions_pending": [{"id": 90, "action": "Update the shared rollout checklist.", "lane_id": None}],
                "blockers_open": [{"id": 91, "description": "Waiting on policy sign-off.", "lane_id": None}],
                "findings_open": [
                    {"id": 92, "description": "Open cross-lane finding.", "severity": "medium", "lane_id": None}
                ],
                "decisions_recent": [
                    {"id": 93, "decision": "Use structured briefs for downstream lanes.", "lane_id": None}
                ],
                "tests_recent": [
                    {"id": 94, "command": "pytest tests/test_cross_lane.py", "passed": 1, "lane_id": None}
                ],
            }
        )

    module.get_handoff_state = fake_get_handoff_state  # type: ignore[attr-defined]
    activity = {
        "lane": {"branch": "codex/p5-frontend", "objective": "Objective"},
        "messages": [
            {
                "id": 1,
                "direction": "orchestrator_to_worker",
                "status": "open",
                "subject": "assignment",
                "message": "Implement the lane slice.",
            }
        ],
        "actions": [],
        "blockers": [],
        "findings": [],
        "reports": [],
    }

    default_prompt, _ = module._build_prompt(
        activity,
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        orchestrator_root=REPO_ROOT,
    )
    expanded_prompt, _ = module._build_prompt(
        activity,
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        orchestrator_root=REPO_ROOT,
        include_global_context=True,
    )

    assert "Escalated Task Context:" not in default_prompt
    assert "Escalated Task Context:" in expanded_prompt
    assert "Update the shared rollout checklist." in expanded_prompt
    assert "Waiting on policy sign-off." in expanded_prompt
    assert calls == [
        global_context_kwargs("phase-5-retention-export-and-audit-controls", limit=module.MAX_GLOBAL_ITEMS)
    ]


def test_build_prompt_reports_prompt_budget_for_optional_context_sections() -> None:
    module = _load_lane_prompt_module()
    module.get_handoff_state = lambda **_: json.dumps(  # type: ignore[attr-defined]
        {
            "ok": True,
            "actions_pending": [{"id": 90, "action": "Update the shared rollout checklist.", "lane_id": None}],
            "blockers_open": [],
            "findings_open": [],
            "decisions_recent": [],
            "tests_recent": [],
        }
    )
    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-frontend", "objective": "Objective"},
            "messages": [
                {
                    "id": 1,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "assignment",
                    "message": "Implement the lane slice.",
                }
            ],
            "actions": [],
            "blockers": [],
            "findings": [],
            "decisions": [{"id": 11, "decision": "Use the compact brief path."}],
            "tests": [{"id": 22, "passed": 1, "command": "pytest tests/test_cross_lane.py"}],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="frontend",
        worktree_path="/tmp/frontend",
        orchestrator_root=REPO_ROOT,
        include_lane_history=True,
        include_global_context=True,
    )

    assert "Recent lane history contributes 2 item(s)" in prompt
    assert "Escalated task context contributes 1 item(s)" in prompt


def test_build_prompt_returns_labeled_context_metrics() -> None:
    module = _load_lane_prompt_module()
    prompt, metrics = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [
                {
                    "id": 1,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "assignment",
                    "message": "Implement the lane slice.",
                }
            ],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
        include_lane_history=True,
    )

    assert prompt
    assert metrics["usage_source"] == "char_estimate"
    assert metrics["prompt_tokens"] == metrics["prompt_tokens_approx"]
    assert metrics["pressure_level"] == metrics["pressure"]
    assert metrics["attribution"]["used_recent_lane_history"] is True
    assert "assignment" in metrics["section_sizes"]


def test_measure_context_utilization_uses_exact_tokenizer_for_supported_backend_and_model() -> None:
    module = _load_lane_prompt_module()

    class _Encoding:
        def encode(self, text: str) -> list[int]:
            return list(range(max(1, len(text) // 10)))

    module.tiktoken = SimpleNamespace(encoding_for_model=lambda _model: _Encoding())

    metrics = module._measure_context_utilization(
        "x" * 500,
        10_000,
        {"assignment": 500},
        backend="codex-cli",
        model="gpt-5-mini",
    )

    assert metrics["usage_source"] == "observed"
    assert metrics["prompt_tokens"] == 50
    assert metrics["prompt_tokens_approx"] is None


def test_measure_context_utilization_labels_tokenizer_estimate_for_unsupported_openai_model() -> None:
    module = _load_lane_prompt_module()

    class _Encoding:
        def encode(self, text: str) -> list[int]:
            return list(range(max(1, len(text) // 8)))

    module.tiktoken = SimpleNamespace(get_encoding=lambda _name: _Encoding())

    metrics = module._measure_context_utilization(
        "x" * 400,
        10_000,
        {"assignment": 400},
        backend="local-model-openai",
        model="gpt-custom-preview",
    )

    assert metrics["usage_source"] == "tokenizer_estimate"
    assert metrics["prompt_tokens"] == 50
    assert metrics["prompt_tokens_approx"] == 50


def test_supports_exact_tiktoken_model_only_for_explicit_exact_models() -> None:
    module = _load_lane_prompt_module()

    assert module._supports_exact_tiktoken_model("gpt-5.4") is True
    assert module._supports_exact_tiktoken_model("o4-mini") is True
    assert module._supports_exact_tiktoken_model("gpt-custom-preview") is False


def test_measure_context_utilization_falls_back_to_char_estimate_when_backend_has_no_tokenizer_path() -> None:
    module = _load_lane_prompt_module()
    module.tiktoken = SimpleNamespace(
        encoding_for_model=lambda _model: (_ for _ in ()).throw(AssertionError("should not be called")),
        get_encoding=lambda _name: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    metrics = module._measure_context_utilization(
        "x" * 400,
        10_000,
        {"assignment": 400},
        backend="claude-code",
        model="claude-sonnet-4-5",
    )

    assert metrics["usage_source"] == "char_estimate"
    assert metrics["prompt_tokens"] == 100
    assert metrics["prompt_tokens_approx"] == 100


def test_build_prompt_includes_runtime_reported_ctx7_and_ace_attribution(monkeypatch) -> None:
    module = _load_lane_prompt_module()
    monkeypatch.setenv("AGENT_HANDOFF_CTX7_QUERY_COUNT", "2")
    monkeypatch.setenv("AGENT_HANDOFF_ACE_GUIDANCE_USED", "true")

    prompt, metrics = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [
                {
                    "id": 1,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "assignment",
                    "message": "Implement the lane slice.",
                }
            ],
            "actions": [],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )

    assert prompt
    assert metrics["attribution"]["used_ace_guidance"] is True
    assert metrics["attribution"]["used_ctx7"] is True
    assert metrics["attribution"]["ctx7_query_count"] == 2


def test_build_summary_lines_color_codes_actionable_items() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines(
        {
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                }
            ],
            "actions": [
                {"id": 72, "status": "pending", "priority": 1, "action": "Implement the backend-domain slice."}
            ],
            "blockers": [{"id": 5, "status": "open", "description": "Database not reachable."}],
            "findings": [
                {
                    "finding_id": "P5-IMPL-01",
                    "status": "open",
                    "severity": "medium",
                    "file_path": "docs/tasks/phase5.md",
                    "line_start": 411,
                    "description": "Checklist item is still unchecked.",
                }
            ],
        }
    )

    assert any("[BLOCKER]" in line and "\x1b[" in line for line in lines)
    assert any("[ACTION P1]" in line and "\x1b[" in line for line in lines)
    assert any("[REVIEW MEDIUM]" in line and "\x1b[" in line for line in lines)
    assert any("[MESSAGE]" in line and "\x1b[" in line for line in lines)


def test_build_summary_lines_idle_message() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines({"messages": [], "actions": [], "blockers": [], "findings": []})
    assert len(lines) == 1
    assert "[IDLE]" in lines[0]


def test_build_prompt_waits_when_worker_handoff_is_newer_than_open_work() -> None:
    module = _load_lane_prompt_module()

    prompt, _ = module._build_prompt(
        {
            "lane": {"branch": "codex/p5-backend-domain", "objective": "Objective"},
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                    "updated_at": "2026-03-15 16:00:00",
                },
                {
                    "id": 26,
                    "direction": "worker_to_orchestrator",
                    "status": "open",
                    "subject": "backend-domain needs guidance",
                    "message": "Already reported back to orchestrator.",
                    "updated_at": "2026-03-15 17:42:46",
                },
            ],
            "actions": [
                {
                    "id": 72,
                    "status": "pending",
                    "priority": 1,
                    "action": "Implement the backend-domain slice.",
                    "updated_at": "2026-03-15 16:00:00",
                }
            ],
            "blockers": [],
            "findings": [],
            "reports": [],
        },
        task_ref="phase-5-retention-export-and-audit-controls",
        lane_id="backend-domain",
        worktree_path="/tmp/backend-domain",
        orchestrator_root=REPO_ROOT,
    )

    assert prompt == module.WAITING_MESSAGE


def test_build_summary_lines_waiting_when_worker_handoff_is_open_and_newer() -> None:
    module = _load_lane_prompt_module()
    lines = module._build_summary_lines(
        {
            "messages": [
                {
                    "id": 8,
                    "direction": "orchestrator_to_worker",
                    "status": "open",
                    "subject": "backend-domain pending next actions",
                    "message": "Pick up action #72.",
                    "updated_at": "2026-03-15 16:00:00",
                },
                {
                    "id": 26,
                    "direction": "worker_to_orchestrator",
                    "status": "open",
                    "subject": "backend-domain needs guidance",
                    "message": "Already reported back to orchestrator.",
                    "updated_at": "2026-03-15 17:42:46",
                },
            ],
            "actions": [
                {
                    "id": 72,
                    "status": "pending",
                    "priority": 1,
                    "action": "Implement the backend-domain slice.",
                    "updated_at": "2026-03-15 16:00:00",
                }
            ],
            "blockers": [],
            "findings": [],
        }
    )

    assert len(lines) == 1
    assert "[WAITING]" in lines[0]


def test_lane_prompt_check_exit_codes_distinguish_idle_and_waiting() -> None:
    module = _load_lane_prompt_module()
    assert module.NO_WORK_EXIT == 3
    assert module.WAITING_EXIT == 4
