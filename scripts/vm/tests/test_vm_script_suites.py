"""Pytest bridge for the VM script suites used by remote verification."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "scripts" / "vm" / "tests"


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
        assert re.fullmatch(r"all cases passed, \d+ skipped", summary)
    print(f"{name}: {summary}")
    assert not any(line.startswith("FAIL:") for line in result.stdout.splitlines())


def test_reap_lane_bash_suite(capsys: pytest.CaptureFixture[str]) -> None:
    with capsys.disabled():
        _run_bash_suite("test_reap_lane.sh")


def test_install_reap_cron_bash_suite(capsys: pytest.CaptureFixture[str]) -> None:
    with capsys.disabled():
        _run_bash_suite("test_install_reap_cron.sh")
