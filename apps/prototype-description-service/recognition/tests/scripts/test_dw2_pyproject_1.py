from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_pytest_testpaths_include_script_test_suites() -> None:
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    collected = [
        item
        for item in result.stdout.splitlines()
        if item.startswith("recognition/tests/scripts/")
    ]

    assert collected, result.stdout + result.stderr
