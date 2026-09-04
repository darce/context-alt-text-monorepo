"""Pytest entry point for the GPU snapshot checker shell contract suite."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The suite spawns seven `make` processes, and this repo's `make` startup
# resolves the active task through four `uvx` package launches. That costs
# ~6s per process on a warm cache and ~15s cold, so the suite legitimately
# needs ~70-120s on a developer laptop while the CI gate host finishes in
# ~30s. This budget exists to catch a hang, not to police wall-clock speed;
# a host-tuned value turns the suite into a hardware-dependent flake.
_DEFAULT_TIMEOUT_SECONDS = 300.0


def test_check_gpu_snapshots_shell_suite() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    suite = repo_root / "scripts/deploy/tests/test-check-gpu-snapshots.sh"

    result = subprocess.run(
        ["/bin/bash", str(suite)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=float(
            os.environ.get(
                "ACX_GPU_SHELL_SUITE_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS
            )
        ),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, f"{suite} exited with {result.returncode}\n{output}"
    assert "PASS: each environment directory must be API-writable" in output
    assert output.rstrip().endswith("ALL PASS")
