from __future__ import annotations

from pathlib import Path

from scripts.check_plan_analyze import check_plan_analyze


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# demo\n")


def _finding(session: str, file_path: str, **overrides) -> dict:
    base = {"session": session, "file_path": file_path}
    base.update(overrides)
    return base


def test_plan_analyze_gate_passes_when_triage_finding_exists_for_target_doc(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")

    captured: dict = {}

    def fake_list_review_findings(**kwargs) -> dict:
        captured.update(kwargs)
        return {
            "ok": True,
            "data": {
                "findings": [
                    _finding("plan-review-docs-plan-20260415", "docs/plan.md"),
                    _finding("plan-analyze-docs-plan-20260415", "docs/plan.md"),
                ]
            },
        }

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        list_review_findings_fn=fake_list_review_findings,
    )

    assert exit_code == 0
    assert "PASS" in message
    assert captured["review_mode"] == "planning"
    assert captured["task_ref"] == "E17-6"


def test_plan_analyze_gate_missing_when_only_other_session_prefixes_exist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        list_review_findings_fn=lambda **_kwargs: {
            "ok": True,
            "data": {
                "findings": [
                    _finding("plan-review-docs-plan-20260415", "docs/plan.md"),
                ]
            },
        },
    )

    assert exit_code == 2
    assert "MISSING" in message


def test_plan_analyze_gate_missing_when_analyze_finding_is_for_other_doc(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "docs" / "plan.md")
    _write(repo / "docs" / "other.md")

    exit_code, message = check_plan_analyze(
        doc_path="docs/plan.md",
        repo_root=repo,
        runtime_factory=lambda _repo: object(),  # type: ignore[arg-type]
        configure_runtime_fn=lambda _runtime: None,
        get_handoff_state_fn=lambda **_kwargs: {"data": {"active": {"task_ref": "E17-6"}}},
        list_review_findings_fn=lambda **_kwargs: {
            "ok": True,
            "data": {
                "findings": [
                    _finding("plan-analyze-docs-other-20260415", "docs/other.md"),
                ]
            },
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
        list_review_findings_fn=lambda **_kwargs: {"ok": False, "data": {"error": "db unavailable"}},
    )

    assert exit_code == 1
    assert "db unavailable" in message
