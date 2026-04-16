from __future__ import annotations

from pathlib import Path

from scripts.check_plan_analyze import check_plan_analyze


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# demo\n")


def test_plan_analyze_gate_passes_when_triage_run_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")

    def fake_review_runs(*, review: dict) -> dict:
        assert review["subject_path"] == "docs/plan.md"
        assert review["review_mode"] == "planning"
        assert review["task_ref"] == "E17-6"
        return {
            "ok": True,
            "data": {
                "runs": [
                    {"session": "plan-review-docs-plan-20260415"},
                    {"session": "plan-analyze-docs-plan-20260415"},
                ]
            },
        }

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        review_runs_fn=fake_review_runs,
    )

    assert exit_code == 0
    assert "PASS" in message


def test_plan_analyze_gate_reports_missing_when_only_formal_review_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        review_runs_fn=lambda **_kwargs: {
            "ok": True,
            "data": {"runs": [{"session": "plan-review-docs-plan-20260415"}]},
        },
    )

    assert exit_code == 2
    assert "MISSING" in message


def test_plan_analyze_gate_reports_api_errors(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        review_runs_fn=lambda **_kwargs: {"ok": False, "data": {"error": "db unavailable"}},
    )

    assert exit_code == 1
    assert "db unavailable" in message
