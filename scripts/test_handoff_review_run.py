from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module():
    script_path = REPO_ROOT / "scripts" / "handoff_review_run.py"
    spec = importlib.util.spec_from_file_location("handoff_review_run_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["handoff_review_run_under_test"] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_subject_path_relative_to_repo() -> None:
    mod = _load_script_module()

    subject = mod._normalize_subject_path(REPO_ROOT, "docs/tasks/example.md")

    assert subject == "docs/tasks/example.md"


def test_record_handoff_review_run_records_and_renders() -> None:
    mod = _load_script_module()
    calls: dict[str, Any] = {}

    def configure_runtime_stub(runtime: object) -> None:
        calls["runtime"] = runtime

    def record_review_run_stub(**kwargs: Any) -> dict[str, Any]:
        calls["record"] = kwargs
        return {"ok": True, "review_run_id": kwargs["review_run_id"]}

    def render_handoff_stub(**kwargs: Any) -> dict[str, Any]:
        calls.setdefault("render", []).append(kwargs)
        return {"ok": True, "kind": kwargs["kind"]}

    def git_value_stub(_repo_root: Path, *args: str) -> str | None:
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "main"
        if args == ("rev-parse", "HEAD"):
            return "deadbeef"
        return None

    result = mod.record_handoff_review_run(
        repo_root=REPO_ROOT,
        review_run_id="planning-review-demo-1",
        session="planning-review-demo",
        subject_path="docs/tasks/example.md",
        subject_kind="task_plan",
        review_mode="planning",
        verdict="pass",
        verdict_decision="copilot_planning_review_demo_pass",
        task_ref="DEMO-1",
        agent="copilot",
        model="gpt-5.4",
        model_label="GPT-5.4",
        reasoning_level="medium",
        runtime_factory=lambda path: ("runtime", path),
        configure_runtime_fn=configure_runtime_stub,
        record_review_run_fn=record_review_run_stub,
        render_handoff_fn=render_handoff_stub,
        git_value_fn=git_value_stub,
    )

    assert calls["record"]["task_ref"] == "DEMO-1"
    assert calls["record"]["subject_path"] == "docs/tasks/example.md"
    assert calls["record"]["actor"] == {
        "agent": "copilot",
        "model": "gpt-5.4",
        "model_label": "GPT-5.4",
        "reasoning_level": "medium",
        "branch": "main",
        "commit_sha": "deadbeef",
    }
    assert calls["render"] == [
        {"kind": "dashboard"},
        {"kind": "current_task", "task_ref": "DEMO-1"},
    ]
    assert result["record_review_run"]["review_run_id"] == "planning-review-demo-1"