"""Regression guard for GPUUX1-CD-02.

The scene startup tests used to pass only in the root worktree, which carries an
untracked `.env` supplying `PGPASSWORD`. In every linked lane worktree they
failed with `InsecureProductionConfigError`, so each offload lane inherited four
unconditional failures it could not distinguish from a real regression.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[2]

_STARTUP_TESTS = [
    "scene/tests/test_describe_route.py::test_create_app_registers_route_and_upload_cap",
    "scene/tests/test_describe_run_reclaim.py::test_startup_reclaim_failure_does_not_block_boot_and_is_wired",
    "scene/tests/test_describe_run_reclaim.py::test_startup_boot_order_reclaim_then_purge_then_snapshot",
    "scene/tests/test_describe_run_reclaim.py::test_startup_purge_or_snapshot_failure_does_not_block_boot",
]


def test_startup_tests_pass_without_any_ambient_credentials() -> None:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("RECOGNITION_", "PG", "ACX_"))}
    env["PATH"] = os.environ.get("PATH", "")
    env["ACX_GPU_SHELL_SUITE_SKIP"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *_STARTUP_TESTS],
        cwd=SERVICE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
