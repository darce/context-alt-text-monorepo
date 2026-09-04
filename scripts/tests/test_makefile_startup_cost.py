from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_fake_uvx(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "uvx-calls.log"
    uvx = bin_dir / "uvx"
    uvx.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$UVX_CALL_LOG"
field=""
previous=""
for argument in "$@"; do
    if [ "$previous" = "--field" ]; then
        field="$argument"
        break
    fi
    previous="$argument"
done
if [ -n "$field" ]; then
    printf 'value-%s\\n' "$field"
fi
""",
        encoding="utf-8",
    )
    uvx.chmod(0o755)
    return bin_dir, call_log


def _make_env(bin_dir: Path, call_log: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "UVX_CALL_LOG": str(call_log),
    }


def _uvx_calls(call_log: Path) -> list[str]:
    if not call_log.exists():
        return []
    return call_log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "real-run"])
def test_task_irrelevant_goal_does_not_launch_uvx(tmp_path: Path, dry_run: bool) -> None:
    bin_dir, call_log = _write_fake_uvx(tmp_path)
    probe = tmp_path / "startup-probe.mk"
    probe.write_text(
        ".PHONY: gpuux-co02-noop\ngpuux-co02-noop:\n\t@env >/dev/null\n",
        encoding="utf-8",
    )
    command = ["make", "-f", "Makefile", "-f", str(probe)]
    if dry_run:
        command.append("-n")
    command.append("gpuux-co02-noop")

    subprocess.run(command, cwd=REPO_ROOT, env=_make_env(bin_dir, call_log), check=True, capture_output=True, text=True)

    # Absolute zero protects the task-irrelevant fast path without a flaky wall-clock threshold.
    assert _uvx_calls(call_log) == []


def test_lazy_lane_fields_keep_values_and_are_memoized(tmp_path: Path) -> None:
    bin_dir, call_log = _write_fake_uvx(tmp_path)
    fields = [
        "branch",
        "worktree_path",
        "title",
        "objective",
        "owned_args",
        "doc_args",
        "test_args",
        "test_command_1",
        "test_command_2",
        "non_goal_args",
        "commit_paths",
        "commit_subject",
        "done_definition",
        "tooling_paths",
    ]
    variables = [
        "LANE_BRANCH",
        "LANE_WORKTREE",
        "LANE_TITLE",
        "LANE_OBJECTIVE",
        "LANE_OWNED_ARGS",
        "LANE_DOC_ARGS",
        "LANE_TEST_ARGS",
        "LANE_TEST_CMD_1",
        "LANE_TEST_CMD_2",
        "LANE_NON_GOAL_ARGS",
        "LANE_COMMIT_PATHS",
        "LANE_COMMIT_SUBJECT",
        "LANE_DONE_DEFINITION",
        "LANE_APP_TOOLING_PATHS",
    ]
    expansion = "|".join(f"$({variable})" for variable in variables)
    probe = tmp_path / "lane-values-probe.mk"
    probe.write_text(
        f".PHONY: gpuux-co02-lane-values\ngpuux-co02-lane-values:\n\t@printf '%s\\n' '{expansion}' '{expansion}'\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "make",
            "-f",
            "Makefile",
            "-f",
            str(probe),
            "gpuux-co02-lane-values",
            "TASK=GPUUX-1",
            "LANE=gpuux-1-h06",
        ],
        cwd=REPO_ROOT,
        env=_make_env(bin_dir, call_log),
        check=True,
        capture_output=True,
        text=True,
    )

    expected = "|".join(f"value-{field}" for field in fields)
    assert completed.stdout.splitlines() == [expected, expected]
    calls = _uvx_calls(call_log)
    assert len(calls) == len(fields)
    for field in fields:
        assert sum(f"--field {field}" in call for call in calls) == 1
