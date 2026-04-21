"""Unit tests for scripts/prod-smoke.sh (E15-3a-BR-04).

Exercises argument parsing and probe failure propagation via subprocess.
No live network; we point the script at an unreachable loopback port and
assert it fails closed.
"""

from __future__ import annotations

import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent / "prod-smoke.sh"


def test_script_is_executable() -> None:
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111


def test_help_exits_zero_and_prints_usage() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "--base-url" in result.stdout


def test_unknown_argument_exits_two() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--no-such-flag"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def test_probes_against_unreachable_host_fail_closed() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--base-url", "http://127.0.0.1:1", "--timeout", "2"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    # The script names each failing path in stderr.
    assert "/health" in result.stderr
    assert "/version" in result.stderr


def test_probe_list_documents_four_core_paths() -> None:
    """The probe list must include the four paths referenced in BR-04."""
    text = SCRIPT.read_text(encoding="utf-8")
    for path in ("/health", "/version", "/recognition/health", "/recognition/settings/test"):
        assert path in text, f"expected {path} in prod-smoke.sh"
