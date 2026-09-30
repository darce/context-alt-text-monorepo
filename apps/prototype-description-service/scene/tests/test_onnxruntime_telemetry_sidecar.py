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

    proc = subprocess.run(
        [sys.executable, "-c", "import onnxruntime"],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0
    assert not list(tmp_path.glob(":memory:*"))
    assert not list(Path.cwd().glob(":memory:*"))
