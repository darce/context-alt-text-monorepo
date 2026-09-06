"""Pytest entry point for the demo smoke-gate Bash contract suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

SUITE = Path(__file__).with_name("test-smoke-gate.sh")
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_smoke_gate_shell_suite() -> None:
    result = subprocess.run(
        ["bash", str(SUITE)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "all assertions passed" in result.stdout, output
