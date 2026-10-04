"""Contract tests for the APP-1 local portal eval runner."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.run_app_portal_evals as runner


def _manifest_payload(
    tmp_path: Path,
    *,
    groups: tuple[str, ...] = ("deterministic",),
    evidence_sink: Path | None = None,
) -> dict[str, Any]:
    cases = [
        {
            "id": f"SC-{index}",
            "group": group,
            "criterion": f"criterion {index}",
            "status": "planned",
            "test": f"recognition/tests/api/test_portal_{index}.py::test_case_{index}",
        }
        for index, group in enumerate(groups, start=1)
    ]
    case_ids = [case["id"] for case in cases]
    return {
        "version": 1,
        "suite_id": "app-1-test-suite",
        "owner": "APP-1",
        "description": "unit-test manifest",
        "command": "pytest",
        "threshold": {"kind": "junit_counts", "max_failures": 0, "max_skipped": 0},
        "evidence_sink": str(evidence_sink or (tmp_path / "results.jsonl")),
        "tags": ["app-1", "test"],
        "cases": cases,
        "release_gates": {
            "beta": {"required_cases": case_ids},
            "expansion": {"required_cases": case_ids[:1]},
            "paid": {"required_cases": case_ids},
        },
    }


def _write_manifest(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _pytest_nodes(command: Sequence[str]) -> list[str]:
    return [argument for argument in command if argument.startswith("recognition/")]


def _junit(*, cases: int = 1, failures: int = 0, skipped: int = 0) -> str:
    testcase_xml: list[str] = []
    for index in range(cases):
        if index < failures:
            child = "<failure message='failed' />"
        elif index < failures + skipped:
            child = "<skipped />"
        else:
            child = ""
        testcase_xml.append(f"<testcase classname='tests' name='case-{index}'>{child}</testcase>")
    return f"<testsuite tests='{cases}' failures='{failures}' skipped='{skipped}'>{''.join(testcase_xml)}</testsuite>"


def _junit_for_nodes(
    nodes: Sequence[str],
    *,
    skipped: Sequence[str] = (),
    failed: Sequence[str] = (),
    errored: Sequence[str] = (),
) -> str:
    """Pytest --junitxml shape: file + classname + name, optional skipped/failure/error."""

    skipped_nodes = set(skipped)
    failed_nodes = set(failed)
    errored_nodes = set(errored)
    testcase_xml: list[str] = []
    for node in nodes:
        file_part, name = node.split("::", 1)
        classname = file_part.replace("/", ".").removesuffix(".py")
        if node in skipped_nodes:
            child = "<skipped type='pytest.skip' message='skipped required case' />"
        elif node in failed_nodes:
            child = "<failure message='failed'>traceback</failure>"
        elif node in errored_nodes:
            child = "<error message='error'>traceback</error>"
        else:
            child = ""
        testcase_xml.append(f"<testcase classname='{classname}' name='{name}' file='{file_part}'>{child}</testcase>")
    return f"<testsuites><testsuite name='pytest' tests='{len(nodes)}'>{''.join(testcase_xml)}</testsuite></testsuites>"


def _write_command_junit(
    command: Sequence[str],
    xml_path: Path,
    *,
    case_count: int | None = None,
    skipped: Sequence[str] = (),
    failed: Sequence[str] = (),
    errored: Sequence[str] = (),
    xml_text: str | None = None,
    mtime: float | None = None,
) -> None:
    if xml_text is not None:
        xml_path.write_text(xml_text, encoding="utf-8")
    else:
        nodes = _pytest_nodes(command)
        if case_count == 0:
            xml_path.write_text(_junit(cases=0), encoding="utf-8")
        elif case_count is not None and case_count != len(nodes):
            xml_path.write_text(_junit(cases=case_count), encoding="utf-8")
        else:
            xml_path.write_text(
                _junit_for_nodes(nodes, skipped=skipped, failed=failed, errored=errored),
                encoding="utf-8",
            )
    if mtime is not None:
        os.utime(xml_path, (mtime, mtime))


def _fake_runner(
    *,
    statuses: dict[str, int] | None = None,
    junit_cases: dict[str, int] | None = None,
    calls: list[tuple[list[str], dict[str, Any]]],
):
    statuses = statuses or {}
    junit_cases = junit_cases or {}

    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="a" * 40, stderr="")
        assert command[:3] == [runner.sys.executable, "-m", "pytest"]
        group = (
            next(argument.split("--", 1)[1] for argument in command if argument.startswith("recognition/tests/"))
            .split("/", 3)[2]
            .split("_", 2)[2]
            .split(".", 1)[0]
        )
        # The command's node id is only a convenient fixture discriminator;
        # the runner itself never infers groups from test names.
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path, case_count=junit_cases.get(group))
        kwargs["stdout"].write(f"child output for {group}\n")
        return SimpleNamespace(returncode=statuses.get(group, 0), stdout=None, stderr=None)

    return fake


def _fake_runner_by_test(
    *,
    statuses: dict[str, int] | None = None,
    junit_cases: dict[str, int] | None = None,
    calls: list[tuple[list[str], dict[str, Any]]],
):
    """Fake subprocess boundary keyed by the test node's portal suffix."""

    statuses = statuses or {}
    junit_cases = junit_cases or {}

    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="b" * 40, stderr="")
        test_node = next(argument for argument in command if argument.startswith("recognition/tests/"))
        group = test_node.rsplit("test_case_", 1)[1]
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path, case_count=junit_cases.get(group))
        kwargs["stdout"].write(f"child output for {group}\n")
        return SimpleNamespace(returncode=statuses.get(group, 0), stdout=None, stderr=None)

    return fake


def test_manifest_missing_required_key_fails_before_any_subprocess(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    del payload["cases"]
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    with pytest.raises(runner.ManifestValidationError, match="missing required keys.*cases"):
        runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_fake_runner(calls=calls))

    assert calls == []


def test_malformed_group_entry_is_rejected_at_load_time(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["group"] = {"name": "deterministic"}
    manifest_path = _write_manifest(tmp_path, payload)

    with pytest.raises(runner.ManifestValidationError, match=r"cases\[0\]\.group"):
        runner.load_manifest(manifest_path)


def test_nonzero_child_status_and_worst_group_status_are_preserved(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("first", "second"))
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    fake = _fake_runner_by_test(
        statuses={"1": 2, "2": 7},
        calls=calls,
    )

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=fake)

    assert status == 7
    pytest_calls = [call for call in calls if call[0][:3] == [runner.sys.executable, "-m", "pytest"]]
    assert [call[1]["timeout"] for call in pytest_calls] == [runner.GROUP_TIMEOUT_SECONDS] * 2


def test_zero_case_junit_report_fails_even_when_child_is_green(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    fake = _fake_runner_by_test(junit_cases={"1": 0}, calls=calls)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=fake)

    assert status == 1
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["groups"][0]["case_count"] == 0
    assert "group produced zero test cases" in evidence["groups"][0]["failure_reasons"]


def test_group_without_executable_tests_fails_without_running_unscoped_pytest(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = "docs/assessments/current/app1-beta-observation-report.md"
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert status == 1
    pytest_calls = [call for call in calls if call[0][:3] == [runner.sys.executable, "-m", "pytest"]]
    assert pytest_calls == []
    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert any(
        "missing required artifact" in reason and "SC-1" in reason
        for reason in evidence["groups"][0]["failure_reasons"]
    )


def test_selected_group_outputs_are_cleaned_without_touching_other_groups(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("selected", "other"))
    manifest_path = _write_manifest(tmp_path, payload)
    manifest = runner.load_manifest(manifest_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    selected_xml, selected_log = runner._artifact_paths(manifest, out_dir, "selected")
    other_xml, other_log = runner._artifact_paths(manifest, out_dir, "other")
    selected_xml.write_text("stale xml", encoding="utf-8")
    selected_log.write_text("stale log", encoding="utf-8")
    other_xml.write_text("keep xml", encoding="utf-8")
    other_log.write_text("keep log", encoding="utf-8")
    calls: list[tuple[list[str], dict[str, Any]]] = []

    runner.run_evals(
        manifest_path,
        groups=["selected"],
        out_dir=out_dir,
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert selected_xml.read_text(encoding="utf-8") != "stale xml"
    assert selected_log.read_text(encoding="utf-8") != "stale log"
    assert other_xml.read_text(encoding="utf-8") == "keep xml"
    assert other_log.read_text(encoding="utf-8") == "keep log"


def test_evidence_has_real_head_sha_and_absolute_artifact_paths(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    out_dir = tmp_path / "out"
    calls: list[tuple[list[str], dict[str, Any]]] = []
    actual_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=runner.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=runner.GIT_TIMEOUT_SECONDS,
    ).stdout.strip()

    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=actual_sha, stderr="")
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path)
        kwargs["stdout"].write("bounded child output\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    runner.run_evals(
        manifest_path,
        out_dir=out_dir,
        environment={"ACX_STRICT_GATE": "1", "ACX_PORTAL_TESTS_REQUIRE_PG": "1"},
        command_runner=fake,
    )

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert evidence["git_sha"] == actual_sha
    assert evidence["environment"] == {
        "ACX_PORTAL_TESTS_REQUIRE_PG": "1",
        "ACX_STRICT_GATE": "1",
    }
    assert all(Path(path).is_absolute() for path in evidence["artifact_paths"])
    assert all(Path(path).is_file() for path in evidence["artifact_paths"])


def test_every_subprocess_call_has_an_explicit_timeout(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert calls
    assert all(call_kwargs.get("timeout") for _command, call_kwargs in calls)


def test_evidence_reads_only_the_bounded_child_output_tail(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((command, kwargs))
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="c" * 40, stderr="")
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path)
        kwargs["stdout"].write("x" * (runner.CAPTURED_TAIL_BYTES + 100))
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=fake)

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    capture = evidence["groups"][0]["output_capture"]
    assert capture["tail_bytes"] == runner.CAPTURED_TAIL_BYTES
    assert capture["tail_limit_bytes"] == runner.CAPTURED_TAIL_BYTES
    assert capture["tail_truncated"] is True
    assert len(capture["tail"].encode("utf-8")) == runner.CAPTURED_TAIL_BYTES


def test_child_credentials_are_redacted_from_log_and_failed_run_evidence(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    secret = "recognition-secret-value"
    credential = "sk-live-abcdefghijklmnop"

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert kwargs["env"]["ACX_RECOGNITION_API_KEY"] == secret
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path)
        kwargs["stdout"].write(f"key={secret}\n")
        kwargs["stdout"].write(f"provider credential {credential}\n")
        raise FileNotFoundError(f"child startup failed after printing {secret}")

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        environment={"ACX_RECOGNITION_API_KEY": secret},
        command_runner=_git_ok_then(handler),
    )

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    log_path = Path(group["output_capture"]["path"])
    log_text = log_path.read_text(encoding="utf-8")
    assert status == runner.COMMAND_NOT_FOUND_EXIT_STATUS
    assert secret not in log_text
    assert credential not in log_text
    assert secret not in group["output_capture"]["tail"]
    assert credential not in group["output_capture"]["tail"]
    assert secret not in " ".join(group["failure_reasons"])
    assert evidence["environment"]["ACX_RECOGNITION_API_KEY"] == "<redacted>"


@pytest.mark.parametrize("environment_key", ["ACX_SERVICE_CREDENTIAL", "ACX_SERVICE_AUTHORIZATION"])
def test_child_credential_variants_are_redacted_from_failed_run(tmp_path: Path, environment_key: str) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_payload(tmp_path))
    secret = "injected-service-value"
    printed_credentials = ["unconfigured-credential-value", "unconfigured-auth-value"]

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert kwargs["env"][environment_key] == secret
        kwargs["stdout"].write(f"service value: {secret}\n")
        kwargs["stdout"].write(f"credential={printed_credentials[0]}\n")
        kwargs["stdout"].write(f"Authorization: Basic {printed_credentials[1]}\n")
        raise FileNotFoundError(f"child startup failed: {secret}")

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        environment={environment_key: secret},
        command_runner=_git_ok_then(handler),
    )

    evidence = _last_evidence(tmp_path)
    log_text = Path(evidence["groups"][0]["output_capture"]["path"]).read_text(encoding="utf-8")
    assert status == runner.COMMAND_NOT_FOUND_EXIT_STATUS
    for value in [secret, *printed_credentials]:
        assert value not in log_text
        assert value not in json.dumps(evidence)
    assert evidence["environment"][environment_key] == "<redacted>"


@pytest.mark.parametrize("exit_status", [0, 1])
def test_invalid_utf8_child_output_still_records_redacted_evidence(tmp_path: Path, exit_status: int) -> None:
    manifest_path = _write_manifest(tmp_path, _manifest_payload(tmp_path))
    secret = "recognition-secret-value"

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path)
        # A subprocess writes bytes directly to the supplied descriptor, bypassing TextIO encoding.
        os.write(kwargs["stdout"].fileno(), b"invalid: \xff\xfe\n" + secret.encode() + b"\n")
        return SimpleNamespace(returncode=exit_status)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        environment={"ACX_RECOGNITION_API_KEY": secret},
        command_runner=_git_ok_then(handler),
    )

    evidence = _last_evidence(tmp_path)
    capture = evidence["groups"][0]["output_capture"]
    log_text = Path(capture["path"]).read_text(encoding="utf-8")
    assert status == exit_status
    assert "invalid: \ufffd\ufffd" in log_text
    assert "invalid: \ufffd\ufffd" in capture["tail"]
    assert "<redacted>" in log_text
    assert secret not in log_text
    assert secret not in json.dumps(evidence)


def _last_evidence(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])


def _git_ok_then(handler):
    def fake(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        return handler(command, **kwargs)

    return fake


def test_required_case_wrong_junit_identity_fails_even_when_counts_are_green(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    declared = payload["cases"][0]["test"]
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(
            command,
            xml_path,
            xml_text=_junit_for_nodes(["recognition/tests/api/test_other.py::test_unrelated"]),
        )
        kwargs["stdout"].write("unrelated passing case\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    assert group["case_count"] == 1
    assert group["pass_count"] == 1
    ledger = group["case_ledger"]
    assert ledger[0]["id"] == "SC-1"
    assert ledger[0]["test"] == declared
    assert ledger[0]["status"] == "not_run"
    assert any("required case" in reason and "SC-1" in reason for reason in group["failure_reasons"])


def test_required_case_skipped_in_junit_cannot_exit_clean(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    declared = payload["cases"][0]["test"]
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path, skipped=[declared])
        kwargs["stdout"].write("skipped\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["status"] == "skipped"
    assert any("skipped" in reason and "SC-1" in reason for reason in group["failure_reasons"])


def test_malformed_junit_fails_and_keeps_truthful_partial_evidence(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        xml_path.write_text("<not-junit", encoding="utf-8")
        kwargs["stdout"].write("parser noise\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    assert evidence["runner_exit_status"] == 1
    assert group["junit_report_found"] is True
    assert group["case_ledger"][0]["status"] == "not_run"
    assert any("cannot parse JUnit" in reason for reason in group["failure_reasons"])
    assert "parser noise" in group["output_capture"]["tail"]


def test_parseable_non_junit_document_cannot_pass_release_gate(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        xml_path.write_text(
            '<results><testcase file="recognition/tests/api/test_portal_1.py" name="test_case_1" /></results>',
            encoding="utf-8",
        )
        kwargs["stdout"].write("pytest completed successfully\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    assert status == 1
    assert evidence["full_suite"] is True
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"
    assert group["case_ledger"][0]["id"] == "SC-1"
    assert group["case_ledger"][0]["status"] == "not_run"
    assert any("not a JUnit document" in reason for reason in group["failure_reasons"])


def test_missing_junit_fails_and_keeps_partial_evidence(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        kwargs["stdout"].write("pytest collected nothing\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["junit_report_found"] is False
    assert group["case_ledger"][0]["status"] == "not_run"
    assert any("JUnit report is missing" in reason for reason in group["failure_reasons"])


def test_stale_junit_mtime_before_run_start_fails(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    manifest_path = _write_manifest(tmp_path, payload)
    past = time.time() - 3600

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path, mtime=past)
        kwargs["stdout"].write("stale report reused\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert any("stale JUnit" in reason for reason in group["failure_reasons"])
    assert group["case_ledger"][0]["status"] == "not_run"


def test_selected_group_does_not_demand_unselected_required_cases(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("selected", "other"))
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        groups=["selected"],
        disposition="slice",
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert status == 0
    evidence = _last_evidence(tmp_path)
    assert evidence["full_suite"] is False
    assert evidence["disposition"] == "slice"
    assert evidence["release_evidence"] is False
    assert evidence["selected_groups"] == ["selected"]
    assert [group["group"] for group in evidence["groups"]] == ["selected"]
    assert evidence["groups"][0]["case_ledger"][0]["id"] == "SC-1"
    assert evidence["groups"][0]["case_ledger"][0]["status"] == "passed"
    assert all("SC-2" not in reason for group in evidence["groups"] for reason in group["failure_reasons"])
    pytest_nodes = [
        argument
        for command, _kwargs in calls
        if command[:3] == [runner.sys.executable, "-m", "pytest"]
        for argument in command
        if argument.startswith("recognition/")
    ]
    assert pytest_nodes == ["recognition/tests/api/test_portal_1.py::test_case_1"]


def test_full_suite_run_is_labeled_full_suite(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("first", "second"))
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 0
    evidence = _last_evidence(tmp_path)
    assert evidence["full_suite"] is True
    assert evidence["disposition"] == "release"
    assert evidence["release_evidence"] is True
    assert evidence["selected_groups"] == ["first", "second"]


def test_reordered_full_group_selection_is_labeled_full_suite(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("deterministic", "browser"))
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        groups=["browser", "deterministic"],
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    evidence = _last_evidence(tmp_path)
    assert status == 0
    assert evidence["full_suite"] is True
    assert evidence["disposition"] == "release"
    assert evidence["release_evidence"] is True
    assert evidence["selected_groups"] == ["browser", "deterministic"]
    assert [group["group"] for group in evidence["groups"]] == ["browser", "deterministic"]


def test_missing_required_artifact_fails_without_greening(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["cases"][0]["artifact"] = "docs/missing-app1-evidence.md"
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["additional_evidence_present"] is False
    assert any("missing required artifact" in reason and "SC-1" in reason for reason in group["failure_reasons"])


def test_additional_evidence_without_artifact_path_cannot_exit_clean(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert any("no artifact" in reason and "SC-1" in reason for reason in group["failure_reasons"])


def test_required_artifact_present_and_matching_junit_can_pass(tmp_path: Path) -> None:
    artifact = tmp_path / "browser-secret-once.json"
    artifact.write_text(json.dumps(_typed_provenance()), encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["cases"][0]["artifact"] = str(artifact)
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 0
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["status"] == "passed"
    assert group["case_ledger"][0]["additional_evidence_present"] is True
    assert group["case_ledger"][0]["additional_evidence_verified"] is True


def test_evidence_only_group_passes_when_required_artifact_exists(tmp_path: Path) -> None:
    artifact = tmp_path / "observation.json"
    artifact.write_text(json.dumps(_typed_provenance()), encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert status == 0
    pytest_calls = [call for call in calls if call[0][:3] == [runner.sys.executable, "-m", "pytest"]]
    assert pytest_calls == []
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["status"] == "passed"
    assert group["exit_status"] == 0


def test_required_case_failure_element_is_not_green(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    declared = payload["cases"][0]["test"]
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(command, xml_path, failed=[declared])
        kwargs["stdout"].write("failed assertion\n")
        return SimpleNamespace(returncode=1, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status >= 1
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["status"] == "failed"
    assert "failed assertion" in group["output_capture"]["tail"]


_FAKE_BY_TEST_SHA = "b" * 40


def _typed_provenance(*, git_sha: str = _FAKE_BY_TEST_SHA) -> dict[str, Any]:
    """F5-shaped provenance JSON: schema_version, commit, command, provenance."""

    return {
        "schema_version": 1,
        "git_sha": git_sha,
        "command": "pytest",
        "runner_exit_status": 0,
        "provenance": {"source": "unit-test", "result": "pass"},
    }


@pytest.mark.parametrize(
    ("runner_exit_status", "provenance_result"),
    [(1, "failed"), (None, "pass"), (0, None), (0, "ambiguous")],
)
def test_provenance_json_without_explicit_success_cannot_pass_a_selected_release_gate(
    tmp_path: Path,
    runner_exit_status: int | None,
    provenance_result: str | None,
) -> None:
    artifact = tmp_path / "failed-run.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "git_sha": _FAKE_BY_TEST_SHA,
        "command": "pytest",
        "provenance": {"source": "unit-test"},
    }
    if runner_exit_status is not None:
        report["runner_exit_status"] = runner_exit_status
    if provenance_result is not None:
        report["provenance"]["result"] = provenance_result
    artifact.write_text(json.dumps(report), encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)

    def clean_repository(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=_FAKE_BY_TEST_SHA, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        pytest.fail(f"evidence-only group unexpectedly started a child: {command}")

    status = runner.run_evals(
        manifest_path,
        gates=["beta"],
        out_dir=tmp_path / "out",
        command_runner=clean_repository,
    )

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    assert status == 1
    assert evidence["full_suite"] is True
    assert evidence["git_dirty"] is False
    assert group["case_ledger"][0]["status"] == "unverified"
    assert group["case_ledger"][0]["additional_evidence_verified"] is False
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"


def test_arbitrary_nonempty_artifact_is_unverified_not_proof(tmp_path: Path) -> None:
    artifact = tmp_path / "not-proof.md"
    artifact.write_text("not proof: arbitrary nonempty text", encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["cases"][0]["artifact"] = str(artifact)
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 1
    ledger = _last_evidence(tmp_path)["groups"][0]["case_ledger"][0]
    assert ledger["status"] == "unverified"
    assert ledger["additional_evidence_present"] is True
    assert ledger["additional_evidence_verified"] is False
    assert any(
        "untyped" in reason or "unverified" in reason
        for reason in _last_evidence(tmp_path)["groups"][0]["failure_reasons"]
    )


def test_release_mode_partial_selection_cannot_report_a_release_pass(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("deterministic", "browser"))
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        groups=["deterministic"],
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    evidence = _last_evidence(tmp_path)
    assert status == 1
    assert evidence["full_suite"] is False
    assert evidence["disposition"] == "release"
    assert evidence["release_evidence"] is False
    assert evidence["groups"][0]["case_ledger"][0]["status"] == "passed"
    assert evidence["groups"][0]["exit_status"] == 0
    assert any("release-mode partial selection" in reason for reason in evidence["failure_reasons"])


def test_explicit_slice_run_may_exit_clean_but_is_not_release_evidence(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path, groups=("deterministic", "browser"))
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        groups=["deterministic"],
        disposition="slice",
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    evidence = _last_evidence(tmp_path)
    assert status == 0
    assert evidence["full_suite"] is False
    assert evidence["disposition"] == "slice"
    assert evidence["release_evidence"] is False
    assert evidence["groups"][0]["case_ledger"][0]["status"] == "passed"


def test_evidence_only_junit_failure_cannot_bypass_threshold(tmp_path: Path) -> None:
    artifact = tmp_path / "failed-evidence.xml"
    xml_text = _junit_for_nodes(
        ["recognition/tests/api/test_portal_1.py::test_case_1"],
        failed=["recognition/tests/api/test_portal_1.py::test_case_1"],
    )
    artifact.write_text(xml_text, encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    artifact.with_suffix(".xml.provenance.json").write_text(
        json.dumps({**_typed_provenance(), "artifact_digest": hashlib.sha256(artifact.read_bytes()).hexdigest()}),
        encoding="utf-8",
    )
    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    assert status == 1
    pytest_calls = [call for call in calls if call[0][:3] == [runner.sys.executable, "-m", "pytest"]]
    assert pytest_calls == []
    group = _last_evidence(tmp_path)["groups"][0]
    assert group["case_ledger"][0]["status"] == "failed"
    assert any("max_failures" in reason or "failure" in reason for reason in group["failure_reasons"])


def test_stale_evidence_only_junit_is_unverified_and_fails_release(tmp_path: Path) -> None:
    artifact = tmp_path / "old-passing-evidence.xml"
    artifact.write_text(
        _junit_for_nodes(["recognition/tests/api/test_portal_1.py::test_case_1"]),
        encoding="utf-8",
    )
    past = time.time() - 3600
    os.utime(artifact, (past, past))
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    ledger = group["case_ledger"][0]
    assert status == 1
    assert evidence["full_suite"] is True
    assert evidence["disposition"] == "release"
    assert ledger["status"] == "unverified"
    assert ledger["additional_evidence_verified"] is False
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"
    assert any("unverified" in reason for reason in evidence["release_gate_results"]["beta"]["reasons"])
    assert any("stale JUnit" in reason and str(artifact) in reason for reason in group["failure_reasons"])


@pytest.mark.parametrize("provenance_sha", [_FAKE_BY_TEST_SHA, "c" * 40])
@pytest.mark.parametrize("commanded", [False, True])
def test_preexisting_junit_requires_current_head_provenance_for_evidence_only(
    tmp_path: Path, provenance_sha: str, commanded: bool
) -> None:
    artifact = tmp_path / "preexisting-evidence.xml"
    artifact.write_text(
        _junit_for_nodes(["recognition/tests/api/test_portal_1.py::test_case_1"]),
        encoding="utf-8",
    )
    past = time.time() - 3600
    os.utime(artifact, (past, past))
    artifact.with_suffix(".xml.provenance.json").write_text(
        json.dumps({
            **_typed_provenance(git_sha=provenance_sha),
            "artifact_digest": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }),
        encoding="utf-8",
    )
    payload = _manifest_payload(tmp_path)
    if not commanded:
        payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["release_gates"]["beta"]["require_sandbox_and_operational_evidence"] = True
    manifest_path = _write_manifest(tmp_path, payload)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=calls),
    )

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    ledger = group["case_ledger"][0]
    verified = not commanded and provenance_sha == _FAKE_BY_TEST_SHA
    assert status == (0 if verified else 1)
    assert ledger["status"] == ("passed" if verified else "unverified")
    assert ledger["additional_evidence_verified"] is verified
    gate = evidence["release_gate_results"]["beta"]
    assert gate["status"] == ("passed" if verified else "failed")
    if commanded:
        assert any("SC-1" in reason and str(artifact) in reason for reason in gate["reasons"])
    pytest_calls = [call for call in calls if call[0][:3] == [runner.sys.executable, "-m", "pytest"]]
    assert len(pytest_calls) == int(commanded)
    if not verified:
        assert any(str(artifact) in reason for reason in group["failure_reasons"])



def test_commanded_junit_artifact_written_during_run_is_verified(tmp_path: Path) -> None:
    artifact = tmp_path / "current-evidence.xml"
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["release_gates"]["beta"]["require_sandbox_and_operational_evidence"] = True
    manifest_path = _write_manifest(tmp_path, payload)

    def write_reports(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        _write_command_junit(command, xml_path)
        artifact.write_bytes(xml_path.read_bytes())
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_git_ok_then(write_reports),
    )

    ledger = _last_evidence(tmp_path)["groups"][0]["case_ledger"][0]
    assert status == 0
    assert ledger["status"] == "passed"
    assert ledger["additional_evidence_verified"] is True
    assert _last_evidence(tmp_path)["release_gate_results"]["beta"]["status"] == "passed"


@pytest.mark.parametrize("digest_field", ["digest", "artifact_digest"])
@pytest.mark.parametrize("digest_kind", ["matching", "zero", "other_file", "missing"])
def test_evidence_only_junit_sidecar_must_identify_report_bytes(
    tmp_path: Path, digest_field: str, digest_kind: str
) -> None:
    artifact = tmp_path / "preexisting-evidence.xml"
    artifact.write_text(
        _junit_for_nodes(["recognition/tests/api/test_portal_1.py::test_case_1"]), encoding="utf-8"
    )
    past = time.time() - 3600
    os.utime(artifact, (past, past))
    provenance = _typed_provenance()
    if digest_kind == "matching":
        provenance[digest_field] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    elif digest_kind == "zero":
        provenance[digest_field] = "0" * 64
    elif digest_kind == "other_file":
        other = tmp_path / "other.xml"
        other.write_text(_junit(cases=2), encoding="utf-8")
        provenance[digest_field] = hashlib.sha256(other.read_bytes()).hexdigest()
    artifact.with_suffix(".xml.provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(artifact)
    payload["cases"][0]["additional_evidence_required"] = True

    status = runner.run_evals(
        _write_manifest(tmp_path, payload),
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    verified = digest_kind == "matching"
    assert status == (0 if verified else 1)
    assert group["case_ledger"][0]["additional_evidence_verified"] is verified
    assert group["case_ledger"][0]["status"] == ("passed" if verified else "unverified")
    assert evidence["release_gate_results"]["beta"]["status"] == ("passed" if verified else "failed")
    if not verified:
        assert any(str(artifact) in reason for reason in group["failure_reasons"])


def test_parametrized_junit_instances_match_declared_base_node(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["test"] = "recognition/tests/test_param.py::test_case"
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(
            command,
            xml_path,
            xml_text=_junit_for_nodes(
                [
                    "recognition/tests/test_param.py::test_case[small]",
                    "recognition/tests/test_param.py::test_case[large]",
                ]
            ),
        )
        kwargs["stdout"].write("parametrized pass\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 0
    evidence = _last_evidence(tmp_path)
    ledger = evidence["groups"][0]["case_ledger"][0]
    assert ledger["status"] == "passed"
    assert ledger["junit_identity"] is not None
    assert "test_case[small]" in ledger["junit_identity"]
    assert "test_case[large]" in ledger["junit_identity"]
    assert evidence["case_results"][0]["execution_status"] == "passed"
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"


def test_any_parametrized_instance_failure_blocks_declared_base_node(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["test"] = "recognition/tests/test_param.py::test_case"
    manifest_path = _write_manifest(tmp_path, payload)
    failed = "recognition/tests/test_param.py::test_case[large]"

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(
            command,
            xml_path,
            xml_text=_junit_for_nodes(
                [
                    "recognition/tests/test_param.py::test_case[small]",
                    failed,
                ],
                failed=[failed],
            ),
        )
        kwargs["stdout"].write("parametrized mixed\n")
        return SimpleNamespace(returncode=1, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 1
    evidence = _last_evidence(tmp_path)
    group = evidence["groups"][0]
    assert group["case_ledger"][0]["status"] == "failed"
    assert any("SC-1" in reason and "failed" in reason for reason in group["failure_reasons"])
    assert evidence["case_results"][0]["execution_status"] == "not_executed_or_failed"
    assert evidence["release_gate_results"]["beta"]["status"] == "failed"


@pytest.mark.parametrize(
    ("failed_nodes", "expected_status", "expected_exit"),
    [
        ((), "passed", 0),
        (("recognition/tests/test_param.py::test_case[small]",), "failed", 1),
    ],
)
def test_overlapping_parametrized_junit_selectors_match_without_consuming_rows(
    tmp_path: Path,
    failed_nodes: tuple[str, ...],
    expected_status: str,
    expected_exit: int,
) -> None:
    payload = _manifest_payload(tmp_path)
    base_node = "recognition/tests/test_param.py::test_case"
    specific_node = f"{base_node}[small]"
    payload["cases"][0]["test"] = base_node
    payload["cases"].append(
        {**payload["cases"][0], "id": "SC-2", "criterion": "criterion 2", "test": specific_node}
    )
    for gate in payload["release_gates"].values():
        gate["required_cases"] = ["SC-1", "SC-2"]
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(
            command,
            xml_path,
            xml_text=_junit_for_nodes(
                [specific_node, f"{base_node}[large]"],
                failed=failed_nodes,
            ),
        )
        kwargs["stdout"].write("overlapping selectors\n")
        return SimpleNamespace(returncode=expected_exit, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == expected_exit
    group = _last_evidence(tmp_path)["groups"][0]
    ledger = group["case_ledger"]
    assert [entry["status"] for entry in ledger] == [expected_status, expected_status]
    assert [entry["test_status"] for entry in ledger] == [expected_status, expected_status]
    assert "test_case[small]" in ledger[0]["junit_identity"]
    assert "test_case[large]" in ledger[0]["junit_identity"]
    assert "test_case[small]" in ledger[1]["junit_identity"]


def test_unsuffixed_release_gate_node_still_passes(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["test"] = "recognition/tests/test_param.py::test_case"
    manifest_path = _write_manifest(tmp_path, payload)

    def handler(command: list[str], **kwargs: Any) -> SimpleNamespace:
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        _write_command_junit(
            command,
            xml_path,
            xml_text=_junit_for_nodes(["recognition/tests/test_param.py::test_case"]),
        )
        kwargs["stdout"].write("unsuffixed pass\n")
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    status = runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=_git_ok_then(handler))

    assert status == 0
    evidence = _last_evidence(tmp_path)
    assert evidence["case_results"][0]["execution_status"] == "passed"
    assert evidence["release_gate_results"]["beta"]["status"] == "passed"


def test_missing_required_artifact_demotes_passing_ledger_status(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0]["additional_evidence_required"] = True
    payload["cases"][0]["artifact"] = str(tmp_path / "does-not-exist.md")
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 1
    ledger = _last_evidence(tmp_path)["groups"][0]["case_ledger"][0]
    assert ledger["status"] == "failed"
    assert ledger["additional_evidence_present"] is False
    assert any(
        "missing required artifact" in reason and "SC-1" in reason
        for reason in _last_evidence(tmp_path)["groups"][0]["failure_reasons"]
    )


def test_evidence_only_missing_artifact_stays_not_run(tmp_path: Path) -> None:
    payload = _manifest_payload(tmp_path)
    payload["cases"][0].pop("test")
    payload["cases"][0]["artifact"] = str(tmp_path / "does-not-exist.xml")
    payload["cases"][0]["additional_evidence_required"] = True
    manifest_path = _write_manifest(tmp_path, payload)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        command_runner=_fake_runner_by_test(calls=[]),
    )

    assert status == 1
    ledger = _last_evidence(tmp_path)["groups"][0]["case_ledger"][0]
    assert ledger["status"] == "not_run"
    assert ledger["additional_evidence_present"] is False
    assert any(
        "missing required artifact" in reason for reason in _last_evidence(tmp_path)["groups"][0]["failure_reasons"]
    )
