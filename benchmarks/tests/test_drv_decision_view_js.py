"""Runs benchmarks/tools/description-review/test/decision-view.test.js under node --test (DESCPICK-1)."""
import shutil
import subprocess
from pathlib import Path

TEST = Path(__file__).resolve().parents[1] / "tools" / "description-review" / "test" / "decision-view.test.js"


def test_node_suite() -> None:
    node = shutil.which("node")
    assert node, "node >= 22 is required on PATH"
    assert TEST.is_file(), f"missing {TEST}"
    run = subprocess.run([node, "--test", str(TEST)], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout[-6000:] + run.stderr[-3000:]
