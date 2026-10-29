"""Pin documented make commands to the installed lifecycle interface."""

import re
import shlex
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = ("CLAUDE.md", ".github/copilot-instructions.md", "Makefile")
OVERLAY = REPO_ROOT / "Makefile.d"


def _review_run_lines(document):
    return [
        (number, line)
        for number, line in enumerate(
            (REPO_ROOT / document).read_text(encoding="utf-8").splitlines(), 1
        )
        if "make handoff-review-run" in line
    ]


def test_documented_make_targets_exist():
    if not OVERLAY.is_dir():
        pytest.skip("Makefile.d:1: lifecycle overlay is not installed")

    targets = set()
    makefiles = [REPO_ROOT / "Makefile", *OVERLAY.glob("*.mk")]
    makefiles.extend((REPO_ROOT / "mk").glob("*.mk"))
    for makefile in makefiles:
        for line in makefile.read_text(encoding="utf-8").splitlines():
            match = re.match(
                r"^([A-Za-z0-9_.%/-]+(?:[ \t]+[A-Za-z0-9_.%/-]+)*)[ \t]*::?(?!=)",
                line,
            )
            if match:
                targets.update(match.group(1).split())
    assert targets, "Makefile:1: no make targets found"

    missing = []
    for document in DOCS[:2]:
        commands = []
        for number, line in enumerate(
            (REPO_ROOT / document).read_text(encoding="utf-8").splitlines(), 1
        ):
            for span in re.findall(r"`([^`]+)`", line):
                match = re.match(
                    r"\s*make\s+((?:-\S+\s+(?:\S+\s+)?)*)([a-z][a-z0-9-]*)",
                    span,
                )
                if match:
                    commands.append((number, match.group(2)))
        assert commands, f"{document}:1: no documented make commands found"
        missing.extend(
            f"{document}:{number}: unknown make target {target!r}"
            for number, target in commands
            if target not in targets
        )
    assert not missing, "\n".join(missing)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="ERRFIX-1 RED errfix-1-doc")
def test_review_run_lines_use_lifecycle_args():
    violations = []
    for document in DOCS:
        lines = _review_run_lines(document)
        assert lines, f"{document}:1: no make handoff-review-run command found"
        for number, line in lines:
            if "LIFECYCLE_ARGS=" not in line or re.search(
                r"\b(TASK_REF|MODE|SUBJECT|SUBJECT_KIND|VERDICT|DECISION|SESSION|RUN_ID)=",
                line,
            ):
                violations.append(
                    f"{document}:{number}: handoff-review-run must pass flags via "
                    "LIFECYCLE_ARGS= without standalone variables"
                )
    assert not violations, "\n".join(violations)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="ERRFIX-1 RED errfix-1-doc")
def test_documented_review_run_forwards_every_placeholder():
    if not OVERLAY.is_dir():
        pytest.skip("Makefile.d:1: lifecycle overlay is not installed")

    commands = [
        (number, span)
        for number, line in _review_run_lines("CLAUDE.md")
        for span in re.findall(r"`([^`]+)`", line)
        if span.startswith("make handoff-review-run")
    ]
    assert commands, "CLAUDE.md:1: no backticked make handoff-review-run command found"
    number, span = commands[0]
    sentinels = []

    def replace_placeholder(match):
        sentinel = f"ERRFIX_S{len(sentinels)}_END"
        sentinels.append(sentinel)
        return sentinel

    span = re.sub(r"<[^<>]+>", replace_placeholder, span)
    assert len(sentinels) >= 3, f"CLAUDE.md:{number}: expected at least three placeholders"
    words = shlex.split(span)
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO_ROOT), *words[1:]],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CLAUDE.md:{number}: documented command exited {result.returncode}\n"
        f"{result.stdout}{result.stderr}"
    )
    missing = [sentinel for sentinel in sentinels if sentinel not in result.stdout]
    assert not missing, f"CLAUDE.md:{number}: placeholders not forwarded: {missing}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="ERRFIX-1 RED errfix-1-doc")
def test_maint_placeholders_are_uppercase():
    occurrences = []
    for document in DOCS:
        text = (REPO_ROOT / document).read_text(encoding="utf-8")
        for match in re.finditer(r"MAINT-((?:<[^<>]+>-?)+)", text):
            number = text.count("\n", 0, match.start()) + 1
            occurrences.append((document, number, match.group(1)))
    assert occurrences, f"{', '.join(f'{doc}:1' for doc in DOCS)}: no MAINT placeholders found"
    violations = [
        f"{document}:{number}: MAINT placeholder must be uppercase: {placeholder}"
        for document, number, suffix in occurrences
        for placeholder in re.findall(r"<[^<>]+>", suffix)
        if not re.fullmatch(r"<[A-Z0-9_]+>", placeholder)
    ]
    assert not violations, "\n".join(violations)


def test_review_run_line_is_identical_across_harness_docs():
    commands = []
    for document in DOCS[:2]:
        lines = _review_run_lines(document)
        assert len(lines) == 1, (
            f"{document}:1: expected exactly one make handoff-review-run line, got {len(lines)}"
        )
        number, line = lines[0]
        commands.append((document, number, line.strip()))
    first, second = commands
    assert first[2] == second[2], (
        f"{first[0]}:{first[1]} and {second[0]}:{second[1]}: "
        "handoff-review-run documentation differs"
    )
