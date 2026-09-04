"""Pytest bridge for the VM script suites used by remote verification."""

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
        timeout=180,
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


def test_reap_bridge_rejects_skips_when_flock_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/flock")
    with pytest.raises(AssertionError, match="skipped 2 cases"):
        _assert_reap_skip_coverage("all cases passed, 2 skipped")
