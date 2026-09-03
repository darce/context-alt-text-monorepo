"""Pytest entry point for the GPU snapshot checker shell contract suite."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_check_gpu_snapshots_shell_suite() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    suite = repo_root / "scripts/deploy/tests/test-check-gpu-snapshots.sh"

    result = subprocess.run(
        ["bash", str(suite)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"{suite} exited with {result.returncode}\n{output}"
    )
