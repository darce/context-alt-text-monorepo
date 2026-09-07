"""Pytest entry point for the GPU evidence exporter Bash contract suite."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SUITE = Path(__file__).with_name("test-export-gpu-evidence.sh")
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_export_gpu_evidence_shell_suite() -> None:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    result = subprocess.run(
        ["bash", str(SUITE)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        # The suite forks a real exporter per scenario and includes a SIGKILL crash case;
        # it takes ~90s on macOS. 30s was sized for the pre-hardening suite.
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "all assertions passed" in result.stdout, output
