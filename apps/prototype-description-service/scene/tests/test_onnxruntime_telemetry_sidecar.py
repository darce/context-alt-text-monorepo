"""Service pytest session must not leave an onnxruntime telemetry sidecar."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def test_pytest_session_disables_onnxruntime_telemetry() -> None:
    assert os.environ.get("ORT_DISABLE_TELEMETRY") == "1"


def test_pytest_session_leaves_no_session_sidecar() -> None:
    onnxruntime_spec = importlib.util.find_spec("onnxruntime")
    sidecar = Path.cwd() / ":memory:.ses"
    assert not sidecar.exists()

    if onnxruntime_spec is not None:
        __import__("onnxruntime")
        assert not sidecar.exists()


def test_telemetry_guard_prevents_stub_session_sidecar(tmp_path: Path) -> None:
    stub_root = tmp_path / "stub"
    stub_package = stub_root / "onnxruntime"
    stub_package.mkdir(parents=True)
    (stub_package / "__init__.py").write_text(
        textwrap.dedent(
            """\
            import os
            from pathlib import Path

            if os.environ.get("ORT_DISABLE_TELEMETRY") != "1":
                Path(":memory:.ses").touch()
            """
        )
    )

    command = [sys.executable, "-c", "import onnxruntime"]
    control_dir = tmp_path / "stub-control"
    control_dir.mkdir()
    control_env = os.environ.copy()
    control_env["PYTHONPATH"] = str(stub_root)
    control_env.pop("ORT_DISABLE_TELEMETRY", None)
    control = subprocess.run(
        command,
        cwd=control_dir,
        env=control_env,
        timeout=120,
        check=False,
    )
    assert control.returncode == 0
    assert (control_dir / ":memory:.ses").exists()

    guarded_dir = tmp_path / "stub-guarded"
    guarded_dir.mkdir()
    guarded_env = os.environ.copy()
    assert guarded_env.get("ORT_DISABLE_TELEMETRY") == "1"
    guarded_env["PYTHONPATH"] = str(stub_root)
    guarded = subprocess.run(
        command,
        cwd=guarded_dir,
        env=guarded_env,
        timeout=120,
        check=False,
    )
    assert guarded.returncode == 0
    assert not (guarded_dir / ":memory:.ses").exists()


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
    # The stub test above is the positive control when this runtime omits the sidecar.

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
