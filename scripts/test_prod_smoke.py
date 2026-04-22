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
    """The probe list must reference real backend routes (E15-3a-BR-08, BR-11).

    `/recognition/settings/test` and `/recognition/describe-minimal` were
    invented in the original BR-04 slice. `/recognition/health` was a real
    route on the April-1st prod image but was removed in commit 6e475cfe
    (E15-2 Slice 2.5b consolidated the health surface to /health + /ready +
    /health/detailed). Replace it with /ready, the canonical readiness
    probe per the consolidated surface.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    for path in ("/health", "/ready", "/version", "/recognition/clusters"):
        assert path in text, f"expected {path} in prod-smoke.sh"
    for bogus in (
        "/recognition/settings/test",
        "/recognition/describe-minimal",
        "/recognition/health",
    ):
        assert bogus not in text, f"removed/bogus path {bogus} must not be in prod-smoke.sh"
