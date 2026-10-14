"""Pytest bridge for the VM script suites used by remote verification."""

import ast
from collections import Counter
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "scripts" / "vm" / "tests"


def _assert_reap_skip_coverage(summary: str) -> None:
    match = re.fullmatch(r"all cases passed, (\d+) skipped", summary)
    assert match
    skipped = int(match.group(1))
    if shutil.which("flock") is None:
        pytest.xfail("flock unavailable; destructive sandbox coverage is reduced")
    assert skipped == 0, (
        f"flock is available but the bash suite skipped {skipped} cases"
    )


def _run_bash_suite(name: str) -> None:
    result = subprocess.run(
        ["bash", str(TESTS / name)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        # test_reap_lane.sh has been observed at ~206s; keep headroom above that.
        timeout=240,
    )
    assert result.returncode == 0, (
        f"{name} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    summary = next(
        (line for line in result.stdout.splitlines() if line.startswith("all cases passed")),
        "",
    )
    assert summary
    if name == "test_reap_lane.sh":
        _assert_reap_skip_coverage(summary)
    print(f"{name}: {summary}")
    assert not any(line.startswith("FAIL:") for line in result.stdout.splitlines())


def test_reap_lane_bash_suite(capsys: pytest.CaptureFixture[str]) -> None:
    with capsys.disabled():
        _run_bash_suite("test_reap_lane.sh")


def test_install_reap_cron_bash_suite(capsys: pytest.CaptureFixture[str]) -> None:
    with capsys.disabled():
        _run_bash_suite("test_install_reap_cron.sh")


@pytest.mark.parametrize(
    "group",
    [
        "tmp_exclusions",
        "tmp_safety_1",
        "tmp_safety_2",
        "tmp_safety_3",
        "docker_journal",
        "installer",
        "failures",
    ],
)
def test_host_hygiene_bash_suite(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, group: str
) -> None:
    monkeypatch.setenv("HYGIENE_TEST_GROUP", group)
    with capsys.disabled():
        _run_bash_suite("test_host_hygiene.sh")


def test_host_hygiene_case_coverage_guard() -> None:
    source = (TESTS / "test_host_hygiene.sh").read_text()
    python_source = source.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    groups = next(
        ast.literal_eval(node.value)
        for node in ast.parse(python_source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "GROUPS"
            for target in node.targets
        )
    )
    parametrized_groups = next(
        mark.args[1]
        for mark in test_host_hygiene_bash_suite.pytestmark
        if mark.name == "parametrize" and mark.args[0] == "group"
    )
    assert set(parametrized_groups) == set(groups), "parametrize/GROUPS mismatch"
    assert len(parametrized_groups) == len(set(parametrized_groups))
    cases = re.findall(r"(?m)^case\('([^']+)',", python_source)
    call_sites = re.findall(r"(?m)^\s*case\s*\(", python_source)
    assert len(cases) == len(call_sites) == 45, (
        "unparsed case registration or case count drift"
    )
    assert len(set(cases)) == len(cases), "duplicate case registration"
    membership = Counter(name for names in groups.values() for name in names)
    assert set(membership) == set(cases), "GROUPS/case coverage mismatch"
    assert all(count == 1 for count in membership.values()), "cases belong to multiple groups"


def test_reap_bridge_rejects_skips_when_flock_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/flock")
    with pytest.raises(AssertionError, match="skipped 2 cases"):
        _assert_reap_skip_coverage("all cases passed, 2 skipped")
