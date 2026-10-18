"""S2R5-19 — make eval-captions cannot pass through the scorer exit.

GNU Make converts every failed recipe to process exit 2. The operator
contract lives on `eval-captions: scorer_exit=<N>`, the status file, and
`scripts/eval-captions.sh` (which can actually exit 3).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_MAKEFILE = _REPO_ROOT / "Makefile"
_WRAPPER = _REPO_ROOT / "scripts" / "eval-captions.sh"
_STATUS = (
    _REPO_ROOT
    / "apps"
    / "prototype-description-service"
    / "scripts"
    / "eval_harness"
    / "out"
    / "eval-captions.status"
)


def _stub_env(tmp_path: Path, scorer_exit: int) -> dict[str, str]:
    stub_dir = tmp_path / f"bin-{scorer_exit}"
    stub_dir.mkdir()
    uv = stub_dir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f"exit {int(scorer_exit)}\n",
        encoding="utf-8",
    )
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = os.environ.copy()
    env["PATH"] = f"{stub_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def _run_make(tmp_path: Path, scorer_exit: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-C", str(_REPO_ROOT), "eval-captions"],
        capture_output=True,
        text=True,
        env=_stub_env(tmp_path, scorer_exit),
    )


def _run_wrapper(tmp_path: Path, scorer_exit: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=_stub_env(tmp_path, scorer_exit),
    )


def test_make_collapses_scorer_failures_to_2_and_prints_marker(tmp_path: Path) -> None:
    """Measured GNU Make contract: 0→0, any scorer failure → make 2."""
    mapping = {}
    for scorer in (0, 1, 2, 3, 7):
        proc = _run_make(tmp_path, scorer)
        mapping[scorer] = proc.returncode
        combined = proc.stdout + proc.stderr
        assert f"eval-captions: scorer_exit={scorer}" in combined, combined
        assert _STATUS.is_file(), "status file must be written"
        assert _STATUS.read_text(encoding="utf-8").strip() == str(scorer)
    assert mapping == {0: 0, 1: 2, 2: 2, 3: 2, 7: 2}


def test_wrapper_preserves_scorer_exit_including_3(tmp_path: Path) -> None:
    """scripts/eval-captions.sh is the command that can honour exit 3."""
    proc = _run_wrapper(tmp_path, 3)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 3, combined
    assert "eval-captions: scorer_exit=3" in combined
    assert _STATUS.read_text(encoding="utf-8").strip() == "3"


def test_makefile_does_not_advertise_make_passthrough_exit_3() -> None:
    """Do not document a 0/1/2/3 make contract Make cannot honour."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    start = text.index("# VLM-2A caption + face eval harness")
    end = text.index(".PHONY: bakeoff-face")
    block = text[start:end]
    assert "GNU Make converts every failed recipe to make" in block
    assert "scorer_exit=" in block
    assert "eval-captions.status" in block
    assert "scripts/eval-captions.sh" in block
    assert "exit 3" in block  # scorer / wrapper, not make
    assert "this target cannot publish that contract as *make's* status" in block
    # The recipe line must not `exit 3` — Make would still report 2.
    recipe_lines = [
        line
        for line in block.splitlines()
        if line.startswith("\t") or line.startswith("        @")
    ]
    recipe = "\n".join(recipe_lines)
    assert "exit 3" not in recipe
    assert "eval-captions.sh" in recipe
