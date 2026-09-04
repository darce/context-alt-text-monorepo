from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE_LIST_MARKER = "gpuux-makefile-list="

# These repository-bootstrap probes are known, non-uvx process launches. New
# eager shell assignments are not added here: they must be made lazy instead.
_ALLOWED_EAGER_SHELL_ASSIGNMENTS = {
    (Path("Makefile"), "WORKTREE_ROOT"),
    (Path("Makefile"), "CURRENT_BRANCH"),
    (Path("Makefile"), "_GIT_COMMON_DIR"),
    (Path("Makefile"), "ORCHESTRATOR_BRANCH"),
}
_EAGER_ASSIGNMENT = re.compile(
    r"^\s*(?:(?:export|override|private)\s+)*"
    r"(?P<variable>[^\s:=]+)\s*(?P<operator>::=|:=|!=)\s*(?P<value>.*)$"
)
_SHELL_EXPANSION = re.compile(r"\$\(\s*shell(?:\s|\))")


@dataclass(frozen=True)
class EagerShellAssignment:
    path: Path
    line: int
    variable: str
    operator: str


@dataclass(frozen=True)
class StartupProbe:
    calls: list[str]
    makefiles: list[Path]
    completed: subprocess.CompletedProcess[str]


def _write_fake_uvx(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
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


def _logical_makefile_lines(path: Path) -> list[tuple[int, str]]:
    logical_lines: list[tuple[int, str]] = []
    pending: list[str] = []
    start_line = 0
    for line_number, physical_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not pending:
            start_line = line_number
        continued = physical_line.rstrip().endswith("\\")
        pending.append(physical_line.rstrip()[:-1] if continued else physical_line)
        if not continued:
            logical_lines.append((start_line, " ".join(pending)))
            pending = []
    if pending:
        logical_lines.append((start_line, " ".join(pending)))
    return logical_lines


def _find_eager_shell_assignments(makefiles: list[Path], *, root: Path) -> list[EagerShellAssignment]:
    violations: list[EagerShellAssignment] = []
    root = Path(os.path.abspath(root))
    unique_makefiles = dict.fromkeys(Path(os.path.abspath(path)) for path in makefiles)
    for makefile in unique_makefiles:
        try:
            relative_path = makefile.relative_to(root)
        except ValueError:
            relative_path = makefile
        inside_define = False
        for line_number, logical_line in _logical_makefile_lines(makefile):
            stripped_line = logical_line.lstrip()
            if stripped_line.startswith("define "):
                inside_define = True
                continue
            if stripped_line == "endef":
                inside_define = False
                continue
            if inside_define or logical_line.startswith("\t"):
                continue
            match = _EAGER_ASSIGNMENT.match(logical_line)
            if match is None:
                continue
            operator = match.group("operator")
            if operator != "!=" and _SHELL_EXPANSION.search(match.group("value")) is None:
                continue
            variable = match.group("variable")
            if (relative_path, variable) in _ALLOWED_EAGER_SHELL_ASSIGNMENTS:
                continue
            violations.append(EagerShellAssignment(relative_path, line_number, variable, operator))
    return violations


def _format_eager_shell_violations(violations: list[EagerShellAssignment]) -> str:
    messages = []
    for violation in violations:
        shell_form = "'!='" if violation.operator == "!=" else f"'{violation.operator}' with '$(shell ...)'"
        messages.append(
            f"{violation.path}:{violation.line}: {violation.variable} uses eager {shell_form}; "
            "make it lazy with '=' and memoize it only when a recipe needs the value"
        )
    return "\n".join(messages)


def _makefiles_from_output(output: str, *, probe: Path) -> list[Path]:
    probe = Path(os.path.abspath(probe))
    for line in output.splitlines():
        if line.startswith(MAKEFILE_LIST_MARKER):
            paths = line.removeprefix(MAKEFILE_LIST_MARKER).split()
            makefiles = [Path(os.path.abspath(REPO_ROOT / path)) for path in paths]
            return [path for path in makefiles if path != probe]
    raise AssertionError("startup probe did not report GNU Make's parsed MAKEFILE_LIST")


def _run_startup_probe(tmp_path: Path, *, dry_run: bool) -> StartupProbe:
    bin_dir, call_log = _write_fake_uvx(tmp_path)
    probe = tmp_path / "startup-probe.mk"
    probe.write_text(
        f"$(info {MAKEFILE_LIST_MARKER}$(MAKEFILE_LIST))\n"
        ".PHONY: gpuux-co02-noop\n"
        "gpuux-co02-noop:\n\t@env >/dev/null\n",
        encoding="utf-8",
    )
    command = ["make", "-f", "Makefile", "-f", str(probe)]
    if dry_run:
        command.append("-n")
    command.append("gpuux-co02-noop")
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=_make_env(bin_dir, call_log),
        check=False,
        capture_output=True,
        text=True,
    )
    return StartupProbe(
        _uvx_calls(call_log),
        _makefiles_from_output(completed.stdout, probe=probe),
        completed,
    )


def _assert_startup_probe(probe: StartupProbe, *, root: Path = REPO_ROOT) -> None:
    violations = _find_eager_shell_assignments(probe.makefiles, root=root)
    if violations:
        raise AssertionError(
            "parsed makefile fragments contain eager shell assignments; these make CI's pristine "
            "checkout report a different startup cost than an overlay-carrying developer worktree:\n"
            f"{_format_eager_shell_violations(violations)}"
        )
    probe.completed.check_returncode()
    assert probe.calls == [], "task-irrelevant startup launched uvx: " + repr(probe.calls)


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "real-run"])
def test_task_irrelevant_goal_does_not_launch_uvx(tmp_path: Path, dry_run: bool) -> None:
    _assert_startup_probe(_run_startup_probe(tmp_path, dry_run=dry_run))


def test_dry_run_and_real_run_startup_verdicts_agree(tmp_path: Path) -> None:
    dry_run = _run_startup_probe(tmp_path / "dry-run", dry_run=True)
    real_run = _run_startup_probe(tmp_path / "real-run", dry_run=False)

    assert dry_run.makefiles == real_run.makefiles, (
        f"dry-run parsed {dry_run.makefiles!r}, but real-run parsed {real_run.makefiles!r}"
    )
    assert dry_run.calls == real_run.calls, (
        f"dry-run launched {dry_run.calls!r}, but real-run launched {real_run.calls!r}"
    )
    _assert_startup_probe(dry_run)
    _assert_startup_probe(real_run)


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


def test_overlay_eager_shell_assignment_reports_actionable_source_line(tmp_path: Path) -> None:
    fragment = tmp_path / "Makefile.d" / "workflows.mk"
    fragment.parent.mkdir()
    fragment.write_text(
        "# synthetic overlay\n\n_WORKBAY_INSTALLED_TOOL_PYTHON := $(shell uvx tool dir)\n",
        encoding="utf-8",
    )

    completed = subprocess.CompletedProcess(["make"], 0, "", "")
    probe = StartupProbe([], [fragment], completed)

    with pytest.raises(AssertionError) as error:
        _assert_startup_probe(probe, root=tmp_path)

    assert str(error.value) == (
        "parsed makefile fragments contain eager shell assignments; these make CI's pristine "
        "checkout report a different startup cost than an overlay-carrying developer worktree:\n"
        "Makefile.d/workflows.mk:3: _WORKBAY_INSTALLED_TOOL_PYTHON uses eager "
        "':=' with '$(shell ...)'; make it lazy with '=' and memoize it only "
        "when a recipe needs the value"
    )


def test_multiline_eager_shell_assignment_is_detected(tmp_path: Path) -> None:
    fragment = tmp_path / "Makefile.d" / "plugins.mk"
    fragment.parent.mkdir()
    fragment.write_text(
        "PLUGIN_STATE := $(shell \\\n\tuvx --from workbay plugins list)\n",
        encoding="utf-8",
    )

    violations = _find_eager_shell_assignments([fragment], root=tmp_path)

    assert [(violation.path, violation.line, violation.variable) for violation in violations] == [
        (Path("Makefile.d/plugins.mk"), 1, "PLUGIN_STATE")
    ]


def test_new_eager_assignment_in_any_parsed_fragment_is_rejected(tmp_path: Path) -> None:
    fragment = tmp_path / "mk" / "new-tool.mk"
    fragment.parent.mkdir()
    fragment.write_text("NEW_TOOL_STATE != uvx --from workbay state\n", encoding="utf-8")

    violations = _find_eager_shell_assignments([fragment], root=tmp_path)

    assert [(violation.path, violation.line, violation.variable) for violation in violations] == [
        (Path("mk/new-tool.mk"), 1, "NEW_TOOL_STATE")
    ]
