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


def _typed_provenance() -> str:
    """Provenance JSON the runner accepts for the fake HEAD this file's runner returns."""

    return json.dumps(
        {
            "schema_version": 1,
            "git_sha": "d" * 40,
            "command": "pytest",
            "provenance": {"source": "unit-test", "result": "pass"},
        }
    )


def _successful_runner(calls: list[tuple[list[str], dict[str, Any]]]):
    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        calls.append((command, kwargs))
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        testcase_xml = []
        for node in (arg for arg in command if "::" in arg and not arg.startswith("-")):
            parts = node.split("::")
            path = parts[0].replace("/", ".")
            if path.endswith(".py"):
                path = path[:-3]
            classname = ".".join([path, *parts[1:-1]])
            testcase_xml.append(f"<testcase classname='{classname}' name='{parts[-1]}'/>")
        xml_path.write_text(
            f"<testsuite tests='{len(testcase_xml)}'>{''.join(testcase_xml)}</testsuite>",
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
    assert any("SC-2" in failure and str(artifact) in failure for failure in evidence["release_gate_failures"])


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

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"
    case_result = next(case for case in evidence["case_results"] if case["case_id"] == "SC-1")
    assert case_result["artifact_present"] is False
    assert any(
        "missing required artifact" in reason and str(artifact) in reason
        for reason in evidence["groups"][0]["failure_reasons"]
    )


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
        parent for parent in Path(__file__).resolve().parents if (parent / "docs" / "scopes").is_dir()
    )
    manifest = runner.load_manifest(repository_root / "docs" / "scopes" / "app-altcontext-beta-clerk-polar-evals.json")

    pending_case_ids = {
        case.case_id for case in manifest.cases if case.additional_evidence_required and case.artifact is None
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
        disposition="slice",
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
    args = runner._build_parser().parse_args(["--manifest", "manifest.json", "--gate", "beta", "--gate", "paid"])
    assert args.gate == ["beta", "paid"]

    with pytest.raises(SystemExit) as exc_info:
        runner._build_parser().parse_args(["--manifest", "manifest.json", "--gate", "unknown"])

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
    artifact.write_text(_typed_provenance(), encoding="utf-8")
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
    artifact.write_text(_typed_provenance(), encoding="utf-8")
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


def test_gate_fails_when_a_required_test_is_missing_from_junit(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [
            _case(
                "SC-PRESENT",
                "selected",
                test="tests/test_suite.py::TestSuite::test_present[param-1]",
            ),
            _case(
                "SC-MISSING",
                "selected",
                test="tests/test_suite.py::TestSuite::test_deselected[param-2]",
            ),
        ],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"] = {
        gate: {"required_cases": ["SC-PRESENT", "SC-MISSING"]} for gate in ("beta", "expansion", "paid")
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    def deselecting_runner(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        xml_path.write_text(
            "<testsuite tests='1'><testcase classname='tests.test_suite.TestSuite' name='test_present[param-1]'/></testsuite>",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=deselecting_runner,
    )

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    case_results = {case["case_id"]: case for case in evidence["case_results"]}
    assert status == 1
    assert case_results["SC-PRESENT"]["execution_status"] == "passed"
    assert case_results["SC-MISSING"]["execution_status"] == "not_executed_or_failed"
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"


def test_pytest_filter_environment_is_stripped_and_recorded(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "selected", test="tests/test_suite.py::test_present")],
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        environment={"PYTEST_ADDOPTS": "-k nothing", "PYTEST_PLUGINS": "hidden_plugin"},
        command_runner=_successful_runner(calls),
    )

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert status == 0
    assert "PYTEST_ADDOPTS" not in calls[0][1]["env"]
    assert "PYTEST_PLUGINS" not in calls[0][1]["env"]
    assert evidence["gate_environment"]["PYTEST_ADDOPTS"] == "-k nothing"
    assert evidence["gate_environment"]["PYTEST_PLUGINS"] == "hidden_plugin"
    assert evidence["groups"][0]["stripped_env_keys"] == ["PYTEST_ADDOPTS", "PYTEST_PLUGINS"]


def _paid_artifact_manifest(tmp_path: Path, artifact: Path) -> Path:
    manifest_path = _manifest(
        tmp_path,
        [_case("APP-SC-20", "paid", artifact=str(artifact))],
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["release_gates"]["paid"]["requires_explicit_live_charge_authorization"] = True
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def test_paid_gate_rejects_empty_app_sc_20_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "app1-paid-release.json"
    artifact.write_text("", encoding="utf-8")
    manifest_path = _paid_artifact_manifest(tmp_path, artifact)

    status = runner.run_evals(
        manifest_path,
        gates=["paid"],
        out_dir=tmp_path / "out",
        command_runner=_successful_runner([]),
    )

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    case_result = evidence["case_results"][0]
    assert status == 1
    assert case_result["artifact_present"] is False
    assert any("APP-SC-20" in reason for reason in evidence["release_gate_results"]["paid"]["reasons"])


def test_paid_gate_requires_and_records_live_charge_authorization(tmp_path: Path) -> None:
    artifact = tmp_path / "app1-paid-release.json"
    artifact.write_text(_typed_provenance(), encoding="utf-8")
    manifest_path = _paid_artifact_manifest(tmp_path, artifact)

    status_without_authorization = runner.run_evals(
        manifest_path,
        gates=["paid"],
        out_dir=tmp_path / "without-authorization",
        command_runner=_successful_runner([]),
    )
    without_authorization = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    args = runner._build_parser().parse_args(
        ["--manifest", str(manifest_path), "--live-charge-authorized-by", "Dana Operator"]
    )
    status_with_authorization = runner.run_evals(
        manifest_path,
        gates=["paid"],
        out_dir=tmp_path / "with-authorization",
        command_runner=_successful_runner([]),
        live_charge_authorized_by=args.live_charge_authorized_by,
    )
    with_authorization = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])

    assert status_without_authorization == 1
    assert (
        "explicit live-charge authorization not given"
        in without_authorization["release_gate_results"]["paid"]["reasons"]
    )
    assert without_authorization["release_gate_results"]["paid"]["live_charge_authorized_by"] is None
    assert status_with_authorization == 0
    assert with_authorization["release_gate_results"]["paid"]["status"] == "passed"
    assert with_authorization["release_gate_results"]["paid"]["live_charge_authorized_by"] == "Dana Operator"


def test_selected_gate_fails_and_records_dirty_tree_paths(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [_case("SC-1", "selected", test="tests/test_suite.py::test_present")],
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []
    successful_runner = _successful_runner(calls)

    def dirty_runner(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(
                returncode=0,
                stdout=" M docs/assessments/dirty-report.md\n",
                stderr="",
            )
        return successful_runner(command, **kwargs)

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=dirty_runner,
    )

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert status == 1
    assert evidence["git_dirty"] is True
    assert evidence["git_dirty_paths"] == ["docs/assessments/dirty-report.md"]
    assert "repository working tree is dirty" in evidence["release_gate_results"]["beta"]["reasons"]
