"""UX-RENDER09: an over-long JSON integer is a fixed explorer refusal through the public ``explore`` CLI.

Each input is the retained public synthetic legacy report, projected by the actual producer and written by
the actual ``write_export``. Only the serialized ``detection.recall`` token is swapped as raw ASCII bytes, so
the test never builds or stringifies a huge Python integer. Every case runs ``explore`` in a fresh
interpreter with Python's default integer-string digit limit, so an uncaught decoder error shows as a
traceback and exit 1. No task-state files or private inputs are read by these tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_firbench_explorer_wire import _projected_wire
from scripts.eval_harness import firbench_comparison_export as producer

APP_ROOT = Path(__file__).resolve().parents[2]
RECALL = b'"recall": 0.504'
NOT_JSON = "invalid explorer export: not valid JSON"


def _export(tmp_path: Path, value: bytes | None) -> Path:
    data = producer.write_export(_projected_wire(), tmp_path / "comparison.json")
    if value is not None:
        raw = data.read_bytes()
        assert raw.count(RECALL) == 1
        data.write_bytes(raw.replace(RECALL, b'"recall": ' + value))
    return data


def _explore(data: Path, out: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(APP_ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("PYTHONINTMAXSTRDIGITS", None)
    return subprocess.run(
        [sys.executable, "-m", "scripts.eval_harness.firbench_cli", "explore", "--data", str(data), "--out", str(out)],
        cwd=APP_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (b"9" * 5000, NOT_JSON),
        (b"-" + b"9" * 5000, NOT_JSON),
        (b"9" * 400, "invalid explorer export: number out of range at reports[0].detection.recall"),
        (b"0.504, " + RECALL, "invalid explorer export: duplicate key"),
        (b"NaN", "invalid explorer export: non-finite number"),
        (b"05", NOT_JSON),
        (b"\xff", "invalid explorer export: not UTF-8 text"),
    ],
    ids=["digits-5000", "negative-digits-5000", "digits-400", "duplicate-key", "non-finite", "malformed", "not-utf8"],
)
def test_explore_refuses_a_bad_producer_export_with_a_fixed_message(tmp_path: Path, value: bytes, message: str) -> None:
    data = _export(tmp_path, value)
    before = data.read_bytes()
    out = tmp_path / "explorer"

    run = _explore(data, out)

    assert (run.returncode, run.stdout, run.stderr.splitlines()) == (2, "", [f"error: {message}"])
    assert data.read_bytes() == before
    assert sorted(tmp_path.iterdir()) == [data]


def test_explore_renders_the_unmodified_producer_export(tmp_path: Path) -> None:
    data = _export(tmp_path, None)
    before = data.read_bytes()
    out = tmp_path / "explorer"

    run = _explore(data, out)

    assert (run.returncode, run.stdout, run.stderr) == (0, f"{out / 'index.html'}\n", "")
    assert (out / "index.html").is_file()
    assert data.read_bytes() == before
