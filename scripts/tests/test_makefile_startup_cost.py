from __future__ import annotations

import os
import re
import subprocess
import warnings
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


@dataclass(frozen=True)
class StartupAssessment:
    repo_violations: list[EagerShellAssignment]
    overlay_violations: list[EagerShellAssignment]


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


def _makefile_path(path: Path, *, root: Path) -> Path:
    absolute_path = Path(os.path.abspath(path))
    try:
        return absolute_path.relative_to(Path(os.path.abspath(root)))
    except ValueError:
        return absolute_path


def _repo_owned_makefiles(makefiles: list[Path], *, root: Path) -> set[Path]:
    root = Path(os.path.abspath(root))
    classified_paths = dict.fromkeys(_makefile_path(path, root=root) for path in makefiles)
    candidate_paths = [path for path in classified_paths if not path.is_absolute()]
    if not candidate_paths:
        return set()

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "--literal-pathspecs",
            "ls-files",
            "--cached",
            "--error-unmatch",
            "-z",
            "--",
            *map(str, candidate_paths),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    # A one means at least one requested path is untracked; git uses 128 for
    # repository or invocation errors, which must not be mistaken for overlays.
    if completed.returncode not in {0, 1}:
        completed.check_returncode()
    return {Path(path) for path in completed.stdout.split("\0") if path}


def _assess_startup_probe(probe: StartupProbe, *, root: Path = REPO_ROOT) -> StartupAssessment:
    repo_owned_makefiles = _repo_owned_makefiles(probe.makefiles, root=root)
    ownership = {
        _makefile_path(path, root=root): _makefile_path(path, root=root) in repo_owned_makefiles
        for path in probe.makefiles
    }
    violations = _find_eager_shell_assignments(probe.makefiles, root=root)
    return StartupAssessment(
        repo_violations=[violation for violation in violations if ownership[violation.path]],
        overlay_violations=[violation for violation in violations if not ownership[violation.path]],
    )


def _overlay_advisory(
    violations: list[EagerShellAssignment], *, calls: list[str] | None = None
) -> str:
    message = (
        "parsed overlay-provided makefile fragments contain eager shell assignments:\n"
        f"{_format_eager_shell_violations(violations)}\n"
        "these files are not owned by this repository; the fix belongs upstream in workbay-system"
    )
    if calls:
        message += (
            "\nthese overlay assignments explain task-irrelevant uvx launches, which are advisory "
            f"for this repository: {calls!r}"
        )
    return message


def _warn_overlay_advisory(
    violations: list[EagerShellAssignment], *, calls: list[str] | None = None
) -> None:
    warnings.warn(_overlay_advisory(violations, calls=calls), pytest.PytestWarning, stacklevel=2)


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


def _assert_startup_probe(
    probe: StartupProbe,
    *,
    root: Path = REPO_ROOT,
    assessment: StartupAssessment | None = None,
) -> None:
    if assessment is None:
        assessment = _assess_startup_probe(probe, root=root)
    if assessment.repo_violations:
        raise AssertionError(
            "parsed makefile fragments contain eager shell assignments; these make CI's pristine "
            "checkout report a different startup cost than an overlay-carrying developer worktree:\n"
            f"{_format_eager_shell_violations(assessment.repo_violations)}"
        )
    probe.completed.check_returncode()
    if assessment.overlay_violations:
        _warn_overlay_advisory(assessment.overlay_violations, calls=probe.calls)
    else:
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
    dry_run_assessment = _assess_startup_probe(dry_run)
    real_run_assessment = _assess_startup_probe(real_run)
    _assert_startup_probe(dry_run, assessment=dry_run_assessment)
    _assert_startup_probe(real_run, assessment=real_run_assessment)

    dry_run_repo_calls = [] if dry_run_assessment.overlay_violations else dry_run.calls
    real_run_repo_calls = [] if real_run_assessment.overlay_violations else real_run.calls
    assert dry_run_repo_calls == real_run_repo_calls, (
        f"dry-run launched repo-owned {dry_run_repo_calls!r}, but real-run launched "
        f"repo-owned {real_run_repo_calls!r}"
    )
    if dry_run.calls != real_run.calls and dry_run_assessment.overlay_violations:
        _warn_overlay_advisory(
            dry_run_assessment.overlay_violations,
            calls=[
                f"dry-run: {dry_run.calls!r}",
                f"real-run: {real_run.calls!r}",
            ],
        )


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


def test_eager_shell_assignment_verdict_depends_on_git_ownership(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    repo_fragment = tmp_path / "mk" / "workflows.mk"
    overlay_fragment = tmp_path / "Makefile.d" / "workflows.mk"
    repo_fragment.parent.mkdir()
    overlay_fragment.parent.mkdir()
    assignment = "# synthetic overlay\n\n_WORKBAY_INSTALLED_TOOL_PYTHON := $(shell uvx tool dir)\n"
    repo_fragment.write_text(assignment, encoding="utf-8")
    overlay_fragment.write_text(assignment, encoding="utf-8")
    ignore_file = tmp_path / ".gitignore"
    ignore_file.write_text("/Makefile.d\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", ".gitignore", "mk/workflows.mk"],
        check=True,
    )

    completed = subprocess.CompletedProcess(["make"], 0, "", "")
    repo_probe = StartupProbe([], [repo_fragment], completed)
    overlay_calls = ["--from mcp-workbay-orchestrator==0.2.0 state"]
    overlay_probe = StartupProbe(overlay_calls, [overlay_fragment], completed)

    with pytest.raises(AssertionError) as error:
        _assert_startup_probe(repo_probe, root=tmp_path)

    assert str(error.value) == (
        "parsed makefile fragments contain eager shell assignments; these make CI's pristine "
        "checkout report a different startup cost than an overlay-carrying developer worktree:\n"
        "mk/workflows.mk:3: _WORKBAY_INSTALLED_TOOL_PYTHON uses eager "
        "':=' with '$(shell ...)'; make it lazy with '=' and memoize it only "
        "when a recipe needs the value"
    )
    with pytest.warns(pytest.PytestWarning) as caught:
        _assert_startup_probe(overlay_probe, root=tmp_path)

    assert len(caught) == 1
    assert str(caught[0].message) == (
        "parsed overlay-provided makefile fragments contain eager shell assignments:\n"
        "Makefile.d/workflows.mk:3: _WORKBAY_INSTALLED_TOOL_PYTHON uses eager "
        "':=' with '$(shell ...)'; make it lazy with '=' and memoize it only "
        "when a recipe needs the value\n"
        "these files are not owned by this repository; the fix belongs upstream in workbay-system\n"
        "these overlay assignments explain task-irrelevant uvx launches, which are advisory "
        f"for this repository: {overlay_calls!r}"
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
