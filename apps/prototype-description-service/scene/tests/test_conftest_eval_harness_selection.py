from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _collect(project_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            *args,
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_eval_harness_collection_is_deselected_by_default_and_selected_explicitly(
    tmp_path: Path,
) -> None:
    service_root = Path(__file__).resolve().parents[2]
    project_root = tmp_path / "minimal-project"
    eval_tests = project_root / "scene" / "tests"
    eval_tests.mkdir(parents=True)
    shutil.copy2(service_root / "conftest.py", project_root / "conftest.py")
    (project_root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = ["scene/tests"]\n',
        encoding="utf-8",
    )
    (eval_tests / "test_eval_harness_probe.py").write_text(
        "def test_eval_harness_probe():\n    pass\n", encoding="utf-8"
    )
    (eval_tests / "test_ordinary_probe.py").write_text(
        "def test_ordinary_probe():\n    pass\n", encoding="utf-8"
    )

    default = _collect(project_root)
    assert default.returncode == 0, default.stdout + default.stderr
    assert "1/2 tests collected (1 deselected)" in default.stdout
    assert "test_eval_harness_probe.py::test_eval_harness_probe" not in default.stdout
    assert "test_ordinary_probe.py::test_ordinary_probe" in default.stdout

    eval_path = "scene/tests/test_eval_harness_probe.py"
    selected_by_path = _collect(project_root, eval_path)
    assert selected_by_path.returncode == 0, (
        selected_by_path.stdout + selected_by_path.stderr
    )
    assert "1 test collected" in selected_by_path.stdout
    assert "(1 deselected)" not in selected_by_path.stdout
    assert "test_eval_harness_probe.py::test_eval_harness_probe" in (
        selected_by_path.stdout
    )

    selected_by_marker = _collect(project_root, "-m", "eval_harness")
    assert selected_by_marker.returncode == 0, (
        selected_by_marker.stdout + selected_by_marker.stderr
    )
    assert "1/2 tests collected (1 deselected)" in selected_by_marker.stdout
    assert "test_eval_harness_probe.py::test_eval_harness_probe" in (
        selected_by_marker.stdout
    )
