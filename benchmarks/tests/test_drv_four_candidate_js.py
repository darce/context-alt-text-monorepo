"""Run the four-candidate operator contract under node --test."""

import shutil
import subprocess
from pathlib import Path

import pytest

TEST = Path(__file__).resolve().parents[1] / "tools" / "description-review" / "test" / "four-candidate.test.js"


def test_node_suite() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the operator contract suite")
    assert TEST.is_file(), f"missing {TEST}"
    run = subprocess.run([node, "--test", str(TEST)], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout[-12000:] + run.stderr[-3000:]
