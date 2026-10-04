"""Regression tests for APP-1 release gate evidence checks."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import scripts.run_app_portal_evals as runner


def _manifest(tmp_path: Path, cases: list[dict[str, Any]]) -> Path:
    case_ids = [case["id"] for case in cases]
    payload = {
        "version": 1,
        "suite_id": "app-1-test-suite",
        "owner": "APP-1",
        "description": "lane regression fixture",
        "command": "pytest",
        "threshold": {"kind": "junit_counts", "max_failures": 0, "max_skipped": 0},
        "evidence_sink": str(tmp_path / "results.jsonl"),
        "tags": ["app-1", "test"],
        "cases": cases,
        "release_gates": {
            "beta": {
                "required_cases": case_ids,
                "require_sandbox_and_operational_evidence": True,
            },
            "expansion": {"required_cases": case_ids},
            "paid": {"required_cases": case_ids},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _case(case_id: str, *, artifact: Path | None = None, additional: bool = False) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": case_id,
        "group": "browser",
        "criterion": f"criterion {case_id}",
        "status": "planned",
        "test": f"tests/test_{case_id.lower()}.py::test_case",
    }
    if artifact is not None:
        case["artifact"] = str(artifact)
    if additional:
        case["additional_evidence_required"] = True
    return case


def _typed_provenance() -> str:
    """Provenance JSON the runner accepts for the fake HEAD this file's runner returns."""

    return json.dumps(
        {
            "schema_version": 1,
            "git_sha": "d" * 40,
            "command": "pytest",
            "runner_exit_status": 0,
            "provenance": {"source": "unit-test", "result": "pass"},
        }
    )


def _successful_runner() -> Any:
    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        test_nodes = [
            arg for arg in command if "::" in arg and not arg.startswith("-")
        ]
        testcases = []
        for node in test_nodes:
            parts = node.split("::")
            path = parts[0].replace("/", ".")
            if path.endswith(".py"):
                path = path[:-3]
            classname = ".".join([path, *parts[1:-1]])
            testcases.append(f"<testcase classname='{classname}' name='{parts[-1]}'/>")
        xml_path.write_text(
            f"<testsuite tests='{len(testcases)}'>{''.join(testcases)}</testsuite>",
            encoding="utf-8",
        )
        kwargs["stdout"].write("test passed\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    return fake


def test_required_test_case_checks_its_own_supplemental_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "earlier-case-report.md"
    artifact.write_text(_typed_provenance(), encoding="utf-8")
    manifest_path = _manifest(
        tmp_path,
        [
            _case("SC-1", artifact=artifact, additional=True),
            _case("SC-2"),
        ],
    )

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(),
    )

    evidence = json.loads(
        (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert status == 0
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"


def test_required_test_case_fails_when_supplemental_artifact_is_missing(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "missing-browser-record.json"
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", artifact=artifact, additional=True)],
    )

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(),
    )

    evidence = json.loads(
        (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    beta_gate = evidence["release_gate_results"]["beta"]
    assert status == 1
    assert beta_gate["status"] == "failed"
    assert any(
        "SC-1" in reason
        and "additional evidence" in reason.lower()
        and str(artifact) in reason
        for reason in beta_gate["reasons"]
    )


def test_required_test_case_without_artifact_path_fails_explicitly(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path, [_case("SC-1", additional=True)])

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(),
    )

    evidence = json.loads(
        (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    beta_gate = evidence["release_gate_results"]["beta"]
    assert status == 1
    assert beta_gate["status"] == "failed"
    assert any(
        "SC-1" in reason and "additional evidence" in reason.lower()
        for reason in beta_gate["reasons"]
    )


def test_git_dirty_state_includes_untracked_nonignored_paths(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="?? docs/new-evidence.txt\n", stderr="")

    dirty, paths = runner._git_dirty_state(fake, repository_root=tmp_path)

    assert commands == [["git", "status", "--porcelain", "--untracked-files=normal"]]
    assert dirty is True
    assert paths == ["docs/new-evidence.txt"]
