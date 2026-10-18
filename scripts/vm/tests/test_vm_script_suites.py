"""Pytest bridge for the VM script suites used by remote verification."""

import ast
from collections import Counter
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "scripts" / "vm" / "tests"
REAP_GROUPS = [
    "locks", "basic_guards", "roots", "archive_guards", "sandbox_races",
    "sandbox_locks", "remote_ttl", "occupancy", "archive_refs", "partial_removal",
    "ref_enumeration", "archive_generations", "archive_verification", "archive_races",
    "worktrees", "sweeps", "freshness", "triage",
]
REAP_PASS_COUNTS = dict(zip(REAP_GROUPS, [
    9, 46, 18, 15, 41, 22, 68, 20, 24, 22, 8, 9, 47, 10, 17, 10, 16, 34,
], strict=True))


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
        # Individual pytest nodes retain the independent fixed 60-second budget.
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
    passes = sum(line.startswith("PASS:") for line in result.stdout.splitlines())
    if name == "test_reap_lane.sh":
        group = os.environ.get("REAP_TEST_GROUP", "")
        expected = REAP_PASS_COUNTS[group] if group else 436
        assert passes > 0, f"reap group {group!r} emitted zero PASS lines"
        assert passes == expected, (
            f"reap group {group!r}: expected {expected} PASS lines, got {passes}"
        )
    print(f"{name}: {summary}; PASS assertions={passes}")
    assert not any(line.startswith("FAIL:") for line in result.stdout.splitlines())


@pytest.mark.parametrize("group", REAP_GROUPS, ids=REAP_GROUPS)
def test_reap_lane_bash_suite(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, group: str
) -> None:
    monkeypatch.setenv("REAP_TEST_GROUP", group)
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
    # Bound group size as well as coverage so synchronized merges cannot hide regressions.
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
    # tmp_exclusions has 10 cases; 10 still rejects every pairwise tmp merge
    # (the smallest combines 6 and 7 cases, totaling 13).
    oversized = {name: len(names) for name, names in groups.items() if len(names) > 10}
    assert not oversized, f"host-hygiene groups must contain at most 10 cases: {oversized}"
    cases = re.findall(r"(?m)^case\('([^']+)',", python_source)
    call_sites = re.findall(r"(?m)^\s*case\s*\(", python_source)
    assert len(cases) == len(call_sites) == 45, (
        "unparsed case registration or case count drift"
    )
    assert len(set(cases)) == len(cases), "duplicate case registration"
    membership = Counter(name for names in groups.values() for name in names)
    assert set(membership) == set(cases), "GROUPS/case coverage mismatch"
    assert all(count == 1 for count in membership.values()), "cases belong to multiple groups"


def test_reap_lane_case_coverage_guard() -> None:
    source = (TESTS / "test_reap_lane.sh").read_text()
    declaration = re.search(r"(?ms)^REAP_GROUPS=\(\n(.*?)^\)\n", source)
    assert declaration, "missing reap group declaration"
    entries = re.findall(r'^  "([a-z_0-9]+):([a-z_0-9 ]*)"$', declaration[1], re.M)
    assert len(entries) == len(declaration[1].splitlines()), "unparsed reap group"
    groups = dict((name, cases.split()) for name, cases in entries)
    assert len(groups) == len(entries), "duplicate reap group"
    assert set(REAP_PASS_COUNTS) == set(groups), "reap PASS pin/group mismatch"
    assert all(count > 0 for count in REAP_PASS_COUNTS.values()), "empty reap PASS pin"
    assert sum(REAP_PASS_COUNTS.values()) == 436, "reap PASS union count drift"
    mark = next(mark for mark in test_reap_lane_bash_suite.pytestmark
                if mark.name == "parametrize" and mark.args[0] == "group")
    assert set(mark.args[1]) == set(groups), "reap parametrize/GROUPS mismatch"
    assert len(mark.args[1]) == len(set(mark.args[1]))
    assert mark.kwargs["ids"] == mark.args[1], "reap ids must equal group names"
    case_source = source.split("# REAP CASE BLOCKS\n", 1)[1].split(
        "# REAP CASE DISPATCH\n", 1
    )[0]
    pattern = re.compile(
        r"(?ms)^reap_case_([a-z_0-9]+)\(\) \{\n(.*?)^\} # REAP_CASE_END \1\n"
    )
    blocks = list(pattern.finditer(case_source))
    assert not pattern.sub("", case_source).strip(), "unregistered reap case body"
    cases = {block[1]: block[2] for block in blocks}
    assert len(cases) == len(blocks) == 18, "reap case block count drift"
    membership = Counter(case for names in groups.values() for case in names)
    assert set(membership) == set(cases), "reap GROUPS/case coverage mismatch"
    assert all(count == 1 for count in membership.values()), "reap case in multiple groups"
    # Singleton measured blocks preserve headroom against the fixed node budget.
    assert all(len(names) == 1 for names in groups.values()), "at most one measured reap block per group"
    assert all(len(cases[names[0]].splitlines()) <= 320 for names in groups.values()), (
        "reap measured blocks must stay within 320 source lines"
    )
    result = subprocess.run(
        ["bash", str(TESTS / "test_reap_lane.sh")], cwd=ROOT,
        env={**os.environ, "REAP_TEST_GROUP": "bogus"},
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode != 0, "unknown reap group must fail closed"
    assert "unknown REAP_TEST_GROUP" in result.stderr


def test_reap_bridge_rejects_skips_when_flock_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/flock")
    with pytest.raises(AssertionError, match="skipped 2 cases"):
        _assert_reap_skip_coverage("all cases passed, 2 skipped")
