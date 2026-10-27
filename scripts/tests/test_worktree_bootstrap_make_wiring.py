from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"
POLICY_MK = REPO_ROOT / "mk" / "worktree-bootstrap.mk"
OVERLAY_LIFECYCLE_MK = REPO_ROOT / "Makefile.d" / "lifecycle.mk"
BOOTSTRAP_SCRIPT = "scripts/workstate/bootstrap_worktree.py"
POLICY_INCLUDE = "include $(ROOT_MAKEFILE_DIR)/mk/worktree-bootstrap.mk"
OVERLAY_INCLUDE = "-include Makefile.d/*.mk"
POLICY_ASSIGNMENT = (
    'LIFECYCLE_WORKTREE_BOOTSTRAP ?= "$(PYTHON)" '
    '"$(ROOT_MAKEFILE_DIR)/scripts/workstate/bootstrap_worktree.py" --worktree .'
)
CMD_PREFIX = "WORKBAY_WORKTREE_BOOTSTRAP_CMD="


def _make_env(**overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    # An outer make (or a developer shell) must not leak flags or the policy
    # value into the make under test.
    for name in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS", "LIFECYCLE_WORKTREE_BOOTSTRAP"):
        env.pop(name, None)
    env.update(overrides)
    return env


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_makefile_includes_policy_once_before_overlay() -> None:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    policy_at = [index for index, line in enumerate(lines) if line.strip() == POLICY_INCLUDE]
    overlay_at = [index for index, line in enumerate(lines) if line.strip() == OVERLAY_INCLUDE]
    assert len(policy_at) == 1, f"Makefile must contain exactly one {POLICY_INCLUDE!r}"
    assert len(overlay_at) == 1, f"Makefile must contain exactly one {OVERLAY_INCLUDE!r}"
    assert policy_at[0] < overlay_at[0], (
        "mk/worktree-bootstrap.mk must be included before Makefile.d/*.mk so its ?= "
        "wins over the overlay's empty LIFECYCLE_WORKTREE_BOOTSTRAP default"
    )
    previous = next(line for line in reversed(lines[: policy_at[0]]) if line.strip() and not line.startswith("#"))
    assert previous.startswith("include $(ROOT_MAKEFILE_DIR)/mk/"), (
        f"mk/worktree-bootstrap.mk must sit among the mk/*.mk includes, found after {previous!r}"
    )


def test_policy_mk_sets_only_the_quote_free_bootstrap_command() -> None:
    text = POLICY_MK.read_text(encoding="utf-8")
    assert "'" not in text, (
        "Makefile.d/lifecycle.mk single-quotes the value as WORKBAY_WORKTREE_BOOTSTRAP_CMD='...'; "
        "a single quote anywhere in mk/worktree-bootstrap.mk risks breaking that recipe"
    )
    assert _code_lines(text) == [POLICY_ASSIGNMENT]
    assert BOOTSTRAP_SCRIPT in POLICY_ASSIGNMENT


@pytest.mark.parametrize(
    ("env_value", "command_line", "expected"),
    [
        pytest.param(None, [], "default", id="default-beats-overlay-empty"),
        pytest.param(None, ["LIFECYCLE_WORKTREE_BOOTSTRAP="], "", id="command-line-disables"),
        pytest.param("/opt/site/bootstrap --site", [], "/opt/site/bootstrap --site", id="environment-wins"),
        pytest.param(
            "/opt/site/bootstrap --site", ["LIFECYCLE_WORKTREE_BOOTSTRAP="], "", id="command-line-beats-environment"
        ),
    ],
)
def test_policy_precedence_against_overlay_empty_default(
    tmp_path: Path, env_value: str | None, command_line: list[str], expected: str
) -> None:
    fake_root = tmp_path / "root"
    fake_python = tmp_path / "venv" / "bin" / "python"
    overlay = tmp_path / "Makefile.d" / "lifecycle.mk"
    overlay.parent.mkdir()
    overlay.write_text("LIFECYCLE_WORKTREE_BOOTSTRAP ?=\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text(
        f"ROOT_MAKEFILE_DIR := {fake_root}\n"
        f"PYTHON ?= {fake_python}\n"
        # -include so a missing policy file reads as the overlay's empty value,
        # the same red the real task-start shows without the policy.
        f"-include {POLICY_MK}\n"
        "include Makefile.d/lifecycle.mk\n"
        ".PHONY: show\n"
        "show:\n"
        "\t@printf '%s\\n' '$(LIFECYCLE_WORKTREE_BOOTSTRAP)'\n",
        encoding="utf-8",
    )
    env = _make_env() if env_value is None else _make_env(LIFECYCLE_WORKTREE_BOOTSTRAP=env_value)
    env.pop("PYTHON", None)
    if expected == "default":
        expected = f'"{fake_python}" "{fake_root}/{BOOTSTRAP_SCRIPT}" --worktree .'

    completed = subprocess.run(
        ["make", "--no-print-directory", "show", *command_line],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == f"{expected}\n", (
        f"LIFECYCLE_WORKTREE_BOOTSTRAP resolved to {completed.stdout.rstrip()!r}, expected {expected!r}"
    )


def test_real_task_start_forwards_bootstrap_command() -> None:
    if not OVERLAY_LIFECYCLE_MK.is_file():
        pytest.skip(
            f"{OVERLAY_LIFECYCLE_MK.relative_to(REPO_ROOT)} is absent: it is the gitignored WorkBay "
            "overlay that defines task-start; run `workbay install` in this checkout to exercise this check"
        )
    completed = subprocess.run(
        ["make", "--no-print-directory", "-n", "task-start", "TASK=ORCA-1", "MODE=claim", "LIFECYCLE_ARGS=--json"],
        cwd=REPO_ROOT,
        env=_make_env(),
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr

    values = [
        token.removeprefix(CMD_PREFIX)
        for line in completed.stdout.splitlines()
        if CMD_PREFIX in line
        for token in shlex.split(line)
        if token.startswith(CMD_PREFIX)
    ]
    assert len(values) == 1, f"expected one {CMD_PREFIX} in task-start dry run:\n{completed.stdout}"
    argv = shlex.split(values[0])
    assert len(argv) == 4, f"{CMD_PREFIX} is {values[0]!r}"
    assert argv[0], f"{CMD_PREFIX} has an empty interpreter: {values[0]!r}"
    assert argv[1].endswith(f"/{BOOTSTRAP_SCRIPT}"), f"{CMD_PREFIX} does not run {BOOTSTRAP_SCRIPT}: {values[0]!r}"
    assert argv[2:] == ["--worktree", "."], f"{CMD_PREFIX} must target the new worktree: {values[0]!r}"
