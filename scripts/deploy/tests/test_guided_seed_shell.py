"""Pytest entry point for the guided-seed selector Bash contract suite (GUIDESEED-1)."""

from __future__ import annotations

import subprocess
from pathlib import Path

SUITE = Path(__file__).with_name("test-guided-seed.sh")
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_guided_seed_shell_suite() -> None:
    result = subprocess.run(
        ["bash", str(SUITE)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "all assertions passed" in result.stdout, output
