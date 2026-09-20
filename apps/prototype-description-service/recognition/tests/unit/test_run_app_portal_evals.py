"""Contract tests for the APP-1 local portal eval runner."""

from __future__ import annotations

import json
import subprocess
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
        group = next(
            argument.split("--", 1)[1]
            for argument in command
            if argument.startswith("recognition/tests/")
        ).split("/", 3)[2].split("_", 2)[2].split(".", 1)[0]
        # The command's node id is only a convenient fixture discriminator;
        # the runner itself never infers groups from test names.
        xml_path = Path(next(argument.split("=", 1)[1] for argument in command if argument.startswith("--junitxml=")))
        cases = junit_cases.get(group, 1)
        xml_path.write_text(_junit(cases=cases), encoding="utf-8")
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
        xml_path.write_text(_junit(cases=junit_cases.get(group, 1)), encoding="utf-8")
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
    assert "group has no executable test cases" in evidence["groups"][0]["failure_reasons"]


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
        xml_path.write_text(_junit(cases=1), encoding="utf-8")
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
        xml_path.write_text(_junit(cases=1), encoding="utf-8")
        kwargs["stdout"].write("x" * (runner.CAPTURED_TAIL_BYTES + 100))
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    runner.run_evals(manifest_path, out_dir=tmp_path / "out", command_runner=fake)

    evidence = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    capture = evidence["groups"][0]["output_capture"]
    assert capture["tail_bytes"] == runner.CAPTURED_TAIL_BYTES
    assert capture["tail_limit_bytes"] == runner.CAPTURED_TAIL_BYTES
    assert capture["tail_truncated"] is True
    assert len(capture["tail"].encode("utf-8")) == runner.CAPTURED_TAIL_BYTES
