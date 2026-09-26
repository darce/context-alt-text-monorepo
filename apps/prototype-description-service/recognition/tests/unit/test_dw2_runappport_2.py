"""Regression tests for supplemental APP-1 release evidence and git state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import scripts.run_app_portal_evals as runner


def _manifest(tmp_path: Path, case: dict[str, Any]) -> Path:
    payload = {
        "version": 1,
        "suite_id": "app-1-test-suite",
        "owner": "APP-1",
        "description": "lane regression fixture",
        "command": "pytest",
        "threshold": {"kind": "junit_counts", "max_failures": 0, "max_skipped": 0},
        "evidence_sink": str(tmp_path / "results.jsonl"),
        "tags": ["app-1", "test"],
        "cases": [case],
        "release_gates": {
            "beta": {
                "required_cases": [case["id"]],
                "require_sandbox_and_operational_evidence": True,
            },
            "expansion": {"required_cases": [case["id"]]},
            "paid": {"required_cases": [case["id"]]},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _successful_runner():
    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        node = next(arg for arg in command if "::" in arg and not arg.startswith("-"))
        parts = node.split("::")
        module = parts[0].replace("/", ".")
        if module.endswith(".py"):
            module = module[:-3]
        classname = ".".join([module, *parts[1:-1]])
        xml_path.write_text(
            f"<testsuite tests='1'><testcase classname='{classname}' name='{parts[-1]}'/></testsuite>",
            encoding="utf-8",
        )
        kwargs["stdout"].write("test passed\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    return fake


def _case(artifact: Path | None) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "SC-1",
        "group": "browser",
        "criterion": "criterion SC-1",
        "status": "planned",
        "test": "tests/test_browser.py::test_flow",
        "additional_evidence_required": True,
    }
    if artifact is not None:
        case["artifact"] = str(artifact)
    return case


def _evidence(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])


def test_required_test_case_fails_when_additional_artifact_is_missing(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-browser-record.json"
    manifest_path = _manifest(tmp_path, _case(artifact))

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(),
    )

    evidence = _evidence(tmp_path)
    beta_gate = evidence["release_gate_results"]["beta"]
    assert status == 1
    assert beta_gate["status"] == "failed"
    assert any(
        "SC-1" in reason and "additional evidence" in reason.lower() and str(artifact) in reason
        for reason in beta_gate["reasons"]
    )


def test_required_test_case_without_artifact_path_fails_explicitly(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path, _case(None))

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(),
    )

    evidence = _evidence(tmp_path)
    beta_gate = evidence["release_gate_results"]["beta"]
    assert status == 1
    assert beta_gate["status"] == "failed"
    assert any("SC-1" in reason and "additional evidence" in reason.lower() for reason in beta_gate["reasons"])


def test_git_dirty_state_includes_untracked_files() -> None:
    commands: list[list[str]] = []

    def git_runner(command: list[str], **_: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="?? docs/new-evidence.txt\n", stderr="")

    dirty, paths = runner._git_dirty_state(git_runner, repository_root=Path("/repo"))

    assert commands == [["git", "status", "--porcelain", "--untracked-files=normal"]]
    assert dirty is True
    assert paths == ["docs/new-evidence.txt"]
