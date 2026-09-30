"""Service pytest session must not leave an onnxruntime telemetry sidecar."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_pytest_session_disables_onnxruntime_telemetry() -> None:
    assert os.environ.get("ORT_DISABLE_TELEMETRY") == "1"


def test_onnxruntime_import_leaves_no_session_sidecar(tmp_path: Path) -> None:
    if importlib.util.find_spec("onnxruntime") is None:
        pytest.skip("onnxruntime is not installed")

    command = [sys.executable, "-c", "import onnxruntime"]

    control_dir = tmp_path / "control"
    control_dir.mkdir()
    control_env = os.environ.copy()
    control_env.pop("ORT_DISABLE_TELEMETRY", None)
    control = subprocess.run(
        command,
        cwd=control_dir,
        env=control_env,
        timeout=120,
        check=False,
    )
    assert control.returncode == 0
    if not (control_dir / ":memory:.ses").exists():
        pytest.skip(
            "installed onnxruntime does not write the sidecar (it appears only "
            "on onnxruntime 1.29 and later), so the guard cannot be exercised here"
        )

    guarded_dir = tmp_path / "guarded"
    guarded_dir.mkdir()
    guarded = subprocess.run(
        command,
        cwd=guarded_dir,
        env=os.environ.copy(),
        timeout=120,
        check=False,
    )
    assert guarded.returncode == 0
    assert not (guarded_dir / ":memory:.ses").exists()
