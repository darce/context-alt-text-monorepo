from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_MAKEFILE = REPO_ROOT / "Makefile"
TARGETS = {
    "lane-check": ("lane-gate.mk", "bootstrap_lane"),
    "lane-intake": ("lane-gate.mk", "lane-report-list"),
    "lane-refresh": ("lane-gate.mk", "Stashing dirty lane state before refresh"),
    "plan-accept": ("plans.mk", "plan_baseline.py"),
}


def _run_make(tmp_path: Path, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "make",
            "-C",
            str(tmp_path),
            "-f",
            str(ROOT_MAKEFILE),
            "-n",
            target,
            "TASK=X",
            "LANE=x",
            "DRY_RUN=1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_overlay(tmp_path: Path) -> None:
    overlay_dir = tmp_path / "Makefile.d"
    overlay_dir.mkdir()
    (overlay_dir / "lane-gate.mk").write_text(
        "".join(f"{target}:\n\t@echo STUB-{target}\n" for target in TARGETS if target != "plan-accept"),
        encoding="utf-8",
    )
    (overlay_dir / "plans.mk").write_text("plan-accept:\n\t@echo STUB-plan-accept\n", encoding="utf-8")


def _assert_no_override_warning(stderr: str) -> None:
    for warning in ("overriding commands", "ignoring old commands", "overriding recipe", "ignoring old recipe"):
        assert warning not in stderr


@pytest.mark.parametrize("target", TARGETS)
def test_plugin_overlay_owns_recipe_without_override_warning(tmp_path: Path, target: str) -> None:
    _write_overlay(tmp_path)

    completed = _run_make(tmp_path, target)
    output = completed.stdout

    assert completed.returncode == 0, completed.stderr or output
    _assert_no_override_warning(completed.stderr)
    assert f"STUB-{target}" in output
    assert TARGETS[target][1] not in output


@pytest.mark.parametrize("target", TARGETS)
def test_tracked_recipe_is_fallback_without_overlay(tmp_path: Path, target: str) -> None:
    completed = _run_make(tmp_path, target)
    output = completed.stdout

    assert completed.returncode == 0, completed.stderr or output
    _assert_no_override_warning(completed.stderr)
    assert TARGETS[target][1] in output
