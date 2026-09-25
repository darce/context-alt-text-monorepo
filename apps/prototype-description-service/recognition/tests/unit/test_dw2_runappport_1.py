"""Regression tests for manifest-backed APP-1 release evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.run_app_portal_evals as runner


def _manifest(tmp_path: Path, cases: list[dict[str, Any]], *, command: str = "pytest") -> Path:
    case_ids = [case["id"] for case in cases]
    payload = {
        "version": 1,
        "suite_id": "app-1-test-suite",
        "owner": "APP-1",
        "description": "lane regression fixture",
        "command": command,
        "threshold": {"kind": "junit_counts", "max_failures": 0, "max_skipped": 0},
        "evidence_sink": str(tmp_path / "results.jsonl"),
        "tags": ["app-1", "test"],
        "cases": cases,
        "release_gates": {
            "beta": {"required_cases": case_ids},
            "expansion": {"required_cases": case_ids},
            "paid": {"required_cases": case_ids},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _case(case_id: str, group: str, *, test: str | None = None, **extra: Any) -> dict[str, Any]:
    case = {
        "id": case_id,
        "group": group,
        "criterion": f"criterion {case_id}",
        "status": "planned",
    }
    if test is not None:
        case["test"] = test
    case.update(extra)
    return case


def _successful_runner(calls: list[tuple[list[str], dict[str, Any]]]):
    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        calls.append((command, kwargs))
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        xml_path.write_text(
            "<testsuite tests='1'><testcase classname='tests' name='case-0'/></testsuite>",
            encoding="utf-8",
        )
        kwargs["stdout"].write("test passed\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    return fake


def test_selected_gate_fails_when_required_case_was_not_executed(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [
            _case("SC-1", "first", test="tests/test_one.py::test_one"),
            _case("SC-2", "second", test="tests/test_two.py::test_two"),
        ],
    )

    status = runner.run_evals(
        manifest_path,
        groups=["first"],
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert "SC-2" in evidence["release_gate_failures"][0]
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"


def test_missing_evidence_only_artifact_prevents_green_run(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-report.md"
    manifest_path = _manifest(
        tmp_path,
        [
            _case("SC-1", "deterministic", test="tests/test_one.py::test_one"),
            _case("SC-2", "deterministic", artifact=str(artifact)),
        ],
    )

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert any(
        "SC-2" in failure and str(artifact) in failure
        for failure in evidence["release_gate_failures"]
    )


def test_missing_supplemental_artifact_does_not_fail_executed_case_gate(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-browser-record.json"
    manifest_path = _manifest(
        tmp_path,
        [
            _case(
                "SC-1",
                "browser",
                test="tests/test_browser.py::test_flow",
                artifact=str(artifact),
                additional_evidence_required=True,
            ),
        ],
    )

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 0
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"
    case_result = next(case for case in evidence["case_results"] if case["case_id"] == "SC-1")
    assert case_result["artifact_present"] is False


def test_additional_evidence_requirement_can_have_pending_artifact(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [
            _case(
                "SC-1",
                "browser",
                test="tests/test_browser.py::test_flow",
                additional_evidence_required=True,
            ),
        ],
    )

    manifest = runner.load_manifest(manifest_path)

    assert manifest.cases[0].artifact is None


def test_real_app1_manifest_loads_with_pending_additional_evidence() -> None:
    repository_root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "docs" / "scopes").is_dir()
    )
    manifest = runner.load_manifest(
        repository_root / "docs" / "scopes" / "app-altcontext-beta-clerk-polar-evals.json"
    )

    pending_case_ids = {
        case.case_id
        for case in manifest.cases
        if case.additional_evidence_required and case.artifact is None
    }
    assert pending_case_ids == {
        "APP-SC-04",
        "APP-SC-09",
        "APP-SC-10",
        "APP-SC-12",
        "APP-SC-14",
        "APP-SC-15",
        "APP-SC-16",
        "APP-SC-17",
        "APP-SC-18",
    }


def test_beta_run_passes_while_expansion_and_paid_artifacts_are_absent(tmp_path: Path) -> None:
    expansion_artifact = tmp_path / "missing-cohort-report.md"
    paid_artifact = tmp_path / "missing-transaction-receipt.json"
    manifest_path = _manifest(
        tmp_path,
        [
            _case("APP-SC-01", "beta", test="tests/test_beta.py::test_beta"),
            _case("APP-SC-19", "expansion", artifact=str(expansion_artifact)),
            _case("APP-SC-20", "paid", artifact=str(paid_artifact)),
        ],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"] = {
        "beta": {"required_cases": ["APP-SC-01"]},
        "expansion": {"required_cases": ["APP-SC-19"]},
        "paid": {"required_cases": ["APP-SC-20"]},
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    status = runner.run_evals(
        manifest_path,
        groups=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 0
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"
    assert evidence["release_gate_results"]["expansion"]["status"] == "failed"
    assert evidence["release_gate_results"]["paid"]["status"] == "failed"


def test_selected_paid_gate_fails_when_app_sc_20_artifact_is_absent(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-transaction-receipt.json"
    manifest_path = _manifest(
        tmp_path,
        [
            _case("APP-SC-01", "beta", test="tests/test_beta.py::test_beta"),
            _case("APP-SC-20", "paid", artifact=str(artifact)),
        ],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"] = {
        "beta": {"required_cases": ["APP-SC-01"]},
        "expansion": {"required_cases": ["APP-SC-01"]},
        "paid": {"required_cases": ["APP-SC-20"]},
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    status = runner.run_evals(
        manifest_path,
        groups=["beta"],
        gates=["paid"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    paid_gate = evidence["release_gate_results"]["paid"]
    assert paid_gate["status"] == "failed"
    assert any("APP-SC-20" in reason and str(artifact) in reason for reason in paid_gate["reasons"])


def test_selected_beta_gate_fails_when_required_evidence_artifact_is_absent(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-beta-observation.md"
    manifest_path = _manifest(
        tmp_path,
        [
            _case("APP-SC-01", "beta", test="tests/test_beta.py::test_beta"),
            _case("APP-SC-04", "study", artifact=str(artifact)),
        ],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"] = {
        "beta": {"required_cases": ["APP-SC-01", "APP-SC-04"]},
        "expansion": {"required_cases": ["APP-SC-04"]},
        "paid": {"required_cases": ["APP-SC-04"]},
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    status = runner.run_evals(
        manifest_path,
        groups=["beta"],
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    beta_gate = evidence["release_gate_results"]["beta"]
    assert beta_gate["status"] == "failed"
    assert any("APP-SC-04" in reason and str(artifact) in reason for reason in beta_gate["reasons"])


def test_gate_option_repeats_and_unknown_name_is_an_argument_error() -> None:
    args = runner._build_parser().parse_args(
        ["--manifest", "manifest.json", "--gate", "beta", "--gate", "paid"]
    )
    assert args.gate == ["beta", "paid"]

    with pytest.raises(SystemExit) as exc_info:
        runner._build_parser().parse_args(
            ["--manifest", "manifest.json", "--gate", "unknown"]
        )

    assert exc_info.value.code == 2


def test_release_gate_cannot_have_no_required_cases(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "deterministic", test="tests/test_one.py::test_one")],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"]["paid"]["required_cases"] = []
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(runner.ManifestValidationError, match="required_cases"):
        runner.load_manifest(manifest_path)


def test_manifest_command_is_used_for_group_subprocess(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "deterministic", test="tests/test_one.py::test_one")],
        command="locked-pytest --from-manifest",
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(calls),
    )

    assert status == 0
    assert calls[0][0][:2] == ["locked-pytest", "--from-manifest"]


def test_manifest_uv_execution_envelope_is_preserved(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "deterministic", test="tests/test_one.py::test_one")],
        command=(
            "cd apps/prototype-description-service && "
            "ACX_PORTAL_TESTS_REQUIRE_PG=1 uv run --locked --extra dev "
            "python scripts/run_app_portal_evals.py --manifest manifest.json --group deterministic"
        ),
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(calls),
    )

    assert status == 0
    command, kwargs = calls[0]
    assert command[:6] == ["uv", "run", "--locked", "--extra", "dev", "pytest"]
    assert kwargs["cwd"] == runner.SERVICE_ROOT
    assert kwargs["env"]["ACX_PORTAL_TESTS_REQUIRE_PG"] == "1"
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["environment"]["ACX_PORTAL_TESTS_REQUIRE_PG"] == "1"


def test_existing_evidence_only_artifact_satisfies_required_case(tmp_path: Path) -> None:
    artifact = tmp_path / "observation-report.md"
    artifact.write_text("observations recorded", encoding="utf-8")
    manifest_path = _manifest(
        tmp_path,
        [
            _case("SC-1", "deterministic", test="tests/test_one.py::test_one"),
            _case("SC-2", "deterministic", artifact=str(artifact)),
        ],
    )

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    assert status == 0
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    case_result = next(case for case in evidence["case_results"] if case["case_id"] == "SC-2")
    assert case_result["declared_status"] == "planned"
    assert case_result["execution_status"] == "evidence_present"
    assert str(artifact) in evidence["artifact_paths"]


def test_evidence_only_group_passes_with_its_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "paid-release-record.json"
    artifact.write_text("release evidence", encoding="utf-8")
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "paid", artifact=str(artifact))],
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_successful_runner(calls),
    )

    assert status == 0
    assert calls == []
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["groups"][0]["evidence_only_group"] is True
    assert evidence["release_gate_failures"] == []
