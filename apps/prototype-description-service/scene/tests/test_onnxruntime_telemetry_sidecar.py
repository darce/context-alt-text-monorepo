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

    control = tmp_path / "control"
    control.mkdir()
    control_env = os.environ.copy()
    control_env.pop("ORT_DISABLE_TELEMETRY", None)
    subprocess.run(
        [sys.executable, "-c", "import onnxruntime"],
        cwd=control,
        env=control_env,
        timeout=120,
        check=False,
    )
    if not (control / ":memory:.ses").exists():
        pytest.skip(
            "the sidecar is not reproducible on this host, so the guard is unobservable here"
        )

    guarded = tmp_path / "guarded"
    guarded.mkdir()
    guarded_proc = subprocess.run(
        [sys.executable, "-c", "import onnxruntime"],
        cwd=guarded,
        env=os.environ.copy(),
        timeout=120,
        check=False,
    )
    assert guarded_proc.returncode == 0
    assert not (guarded / ":memory:.ses").exists()
