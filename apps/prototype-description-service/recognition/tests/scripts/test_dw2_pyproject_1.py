from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_testpaths_include_script_test_suites() -> None:
    project_root = Path(__file__).resolve().parents[3]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text())
    pytest_config = pyproject["tool"]["pytest"]["ini_options"]
    testpaths = set(pytest_config["testpaths"])

    assert "recognition/tests/scripts" in testpaths
    assert "scripts/bench/tests" in testpaths
    assert "scripts" in pytest_config["norecursedirs"]
