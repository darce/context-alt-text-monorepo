"""Tests for the task-plan finding-list guard hook.

Run with: ``python3 -m pytest scripts/hooks/test_guard_task_plan_findings.py``
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HOOK_SCRIPT = Path(__file__).parent / "guard-task-plan-findings.py"

_spec = importlib.util.spec_from_file_location("guard_task_plan_findings", HOOK_SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_detect_finding_runs = _mod._detect_finding_runs
_path_should_be_scanned = _mod._path_should_be_scanned


# ---------------------------------------------------------------------------
# _detect_finding_runs — heuristic correctness
# ---------------------------------------------------------------------------


def test_detects_three_consecutive_task_prefixed_findings() -> None:
    text = (
        "## Findings\n"
        "\n"
        "- AOMCP-3-BR-04: Description here.\n"
        "- AOMCP-3-BR-05: Another finding.\n"
        "- AOMCP-3-BR-06: Yet another.\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1
    start_line, ids = runs[0]
    assert start_line == 3
    assert ids == ["AOMCP-3-BR-04", "AOMCP-3-BR-05", "AOMCP-3-BR-06"]


def test_detects_three_consecutive_severity_shorthand_findings() -> None:
    text = (
        "- **H-1**: severity high finding\n"
        "- **M-2**: severity medium finding\n"
        "- **L-3**: severity low finding\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1
    assert runs[0][1] == ["H-1", "M-2", "L-3"]


def test_two_findings_do_not_trigger() -> None:
    text = (
        "- H-1: only two\n"
        "- M-2: of these\n"
        "- not a finding bullet\n"
    )
    assert _detect_finding_runs(text) == []


def test_inline_mention_does_not_trigger() -> None:
    text = (
        "We fixed AOMCP-3-BR-04 in this commit.\n"
        "\n"
        "The reviewer flagged H-1 and L-3 as related, but only H-1 blocks merge.\n"
    )
    assert _detect_finding_runs(text) == []


def test_continuation_lines_do_not_break_run() -> None:
    text = (
        "- AOMCP-3-BR-04: Description that wraps\n"
        "  onto a continuation line.\n"
        "- AOMCP-3-BR-05: Another finding\n"
        "  with more detail.\n"
        "- AOMCP-3-BR-06: Final one.\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1
    assert runs[0][1] == ["AOMCP-3-BR-04", "AOMCP-3-BR-05", "AOMCP-3-BR-06"]


def test_blank_line_resets_run() -> None:
    text = (
        "- AOMCP-3-BR-04: First.\n"
        "- AOMCP-3-BR-05: Second.\n"
        "\n"
        "- AOMCP-3-BR-06: Third (separate run).\n"
    )
    assert _detect_finding_runs(text) == []


def test_non_finding_bullet_resets_run() -> None:
    text = (
        "- AOMCP-3-BR-04: First.\n"
        "- AOMCP-3-BR-05: Second.\n"
        "- Some other note.\n"
        "- AOMCP-3-BR-06: Third.\n"
    )
    assert _detect_finding_runs(text) == []


def test_em_dash_separator_matches() -> None:
    text = (
        "- AOMCP-3-BR-04 \u2014 dash separator\n"
        "- AOMCP-3-BR-05 \u2014 dash separator\n"
        "- AOMCP-3-BR-06 \u2014 dash separator\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1


def test_e_prefixed_epic_id_matches() -> None:
    text = (
        "- E15-7-BR-01: epic-prefixed task finding\n"
        "- E15-7-BR-02: another\n"
        "- E15-7-BR-03: a third\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 1


def test_finds_multiple_independent_runs() -> None:
    text = (
        "- AOMCP-3-BR-04: first run a\n"
        "- AOMCP-3-BR-05: first run b\n"
        "- AOMCP-3-BR-06: first run c\n"
        "\n"
        "Some prose between.\n"
        "\n"
        "- H-1: second run a\n"
        "- H-2: second run b\n"
        "- H-3: second run c\n"
    )
    runs = _detect_finding_runs(text)
    assert len(runs) == 2


# ---------------------------------------------------------------------------
# _path_should_be_scanned — path filter
# ---------------------------------------------------------------------------


def test_path_filter_includes_docs_tasks() -> None:
    assert _path_should_be_scanned("docs/tasks/12.0/foo.md")


def test_path_filter_includes_packages_docs_tasks() -> None:
    assert _path_should_be_scanned(
        "packages/agent-orchestrator-mcp/docs/tasks/AOMCP-3-tool-surface-consolidation-task-plan.md"
    )


def test_path_filter_includes_docs_epics() -> None:
    assert _path_should_be_scanned("docs/epics/v0.4.0/public-demo.md")


def test_path_filter_includes_task_plan_filename_anywhere() -> None:
    assert _path_should_be_scanned("packages/foo/some-task-plan.md")


def test_path_filter_excludes_claude_md() -> None:
    assert not _path_should_be_scanned("CLAUDE.md")


def test_path_filter_excludes_instructions_md() -> None:
    assert not _path_should_be_scanned("docs/agentic/instructions.md")


def test_path_filter_excludes_changelog() -> None:
    assert not _path_should_be_scanned("packages/agent-handoff-mcp/CHANGELOG.md")


def test_path_filter_excludes_non_markdown() -> None:
    assert not _path_should_be_scanned("foo.py")
    assert not _path_should_be_scanned("docs/tasks/12.0/foo.txt")


# ---------------------------------------------------------------------------
# end-to-end stdin invocation (Claude Code hook protocol)
# ---------------------------------------------------------------------------


def _run_hook(payload: dict, cwd: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=5,
        cwd=cwd,
    )
    return proc.returncode, proc.stderr


def test_hook_blocks_write_with_finding_list(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_input": {
            "file_path": str(target),
            "content": (
                "## Findings\n\n"
                "- AOMCP-3-BR-04: First.\n"
                "- AOMCP-3-BR-05: Second.\n"
                "- AOMCP-3-BR-06: Third.\n"
            ),
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 2
    assert "Pasted review-finding list detected" in stderr
    assert "AOMCP-3-BR-04" in stderr
    assert "review_findings" in stderr  # actionable hint


def test_hook_allows_write_without_finding_list(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_input": {
            "file_path": str(target),
            "content": (
                "# Task Plan\n\n"
                "## Slice 1\n"
                "- Implement foo\n"
                "- Test bar\n"
                "- Document baz\n"
            ),
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 0
    assert stderr == ""


def test_hook_allows_write_to_unscoped_path(tmp_path: Path) -> None:
    target = tmp_path / "CLAUDE.md"
    payload = {
        "tool_input": {
            "file_path": str(target),
            "content": (
                "## Findings\n\n"
                "- AOMCP-3-BR-04: First.\n"
                "- AOMCP-3-BR-05: Second.\n"
                "- AOMCP-3-BR-06: Third.\n"
            ),
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 0


def test_hook_blocks_edit_with_new_string(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_input": {
            "file_path": str(target),
            "old_string": "placeholder",
            "new_string": (
                "- **H-1**: severity high finding\n"
                "- **M-2**: severity medium finding\n"
                "- **L-3**: severity low finding\n"
            ),
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 2
    assert "H-1" in stderr


def test_hook_blocks_incremental_edit_completing_three_bullet_run(tmp_path: Path) -> None:
    """Regression for AHMCP-14-BR-04.

    A task plan that already contains two finding bullets must be unable to
    grow a third via an Edit whose ``new_string`` adds a single bullet. The
    hook must scan the post-edit document, not just the inserted fragment.
    """
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "## Findings\n"
        "\n"
        "- AOMCP-3-BR-04: First.\n"
        "- AOMCP-3-BR-05: Second.\n"
        "- placeholder\n",
        encoding="utf-8",
    )
    payload = {
        "tool_input": {
            "file_path": str(target),
            "old_string": "- placeholder\n",
            "new_string": "- AOMCP-3-BR-06: Third.\n",
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 2, f"expected hook to block, got rc={rc}, stderr={stderr!r}"
    assert "AOMCP-3-BR-06" in stderr
    assert "Pasted review-finding list detected" in stderr


def test_hook_allows_edit_that_does_not_form_finding_run(tmp_path: Path) -> None:
    """An Edit on a clean task plan that adds prose must still be allowed."""
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "# Task Plan\n\n## Slice 1\n- Implement foo\n- Test bar\n",
        encoding="utf-8",
    )
    payload = {
        "tool_input": {
            "file_path": str(target),
            "old_string": "- Test bar\n",
            "new_string": "- Test bar\n- Document baz\n",
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 0, f"expected hook to allow, got rc={rc}, stderr={stderr!r}"


def test_hook_falls_back_to_new_string_when_file_missing(tmp_path: Path) -> None:
    """When the target file doesn't exist, the hook still scans new_string."""
    target = tmp_path / "docs" / "tasks" / "12.0" / "does-not-exist-task-plan.md"
    target.parent.mkdir(parents=True)
    payload = {
        "tool_input": {
            "file_path": str(target),
            "old_string": "placeholder",
            "new_string": (
                "- AOMCP-3-BR-04: a\n"
                "- AOMCP-3-BR-05: b\n"
                "- AOMCP-3-BR-06: c\n"
            ),
        }
    }
    rc, stderr = _run_hook(payload)
    assert rc == 2
    assert "AOMCP-3-BR-04" in stderr


def test_hook_replace_all_simulates_global_replacement(tmp_path: Path) -> None:
    """replace_all=True must apply to every occurrence in the simulated scan."""
    target = tmp_path / "docs" / "tasks" / "12.0" / "fake-task-plan.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "## A\n- TOK\n\n## B\n- TOK\n\n## C\n- TOK\n",
        encoding="utf-8",
    )
    payload = {
        "tool_input": {
            "file_path": str(target),
            "old_string": "- TOK",
            "new_string": "- AOMCP-3-BR-04: filled in",
            "replace_all": True,
        }
    }
    # Each TOK becomes a single finding bullet, but they sit in separate
    # sections so blank lines reset the run. None of the runs reach three
    # consecutive bullets, so the hook must allow.
    rc, stderr = _run_hook(payload)
    assert rc == 0, f"expected allow, got rc={rc}, stderr={stderr!r}"


# ---------------------------------------------------------------------------
# --scan-repo mode (regression for AHMCP-14-BR-03)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def _init_fake_repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _git(root, "commit", "--allow-empty", "-m", "init", "-q")


def _run_hook_in(cwd: Path, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_scan_repo_catches_task_plan_outside_hard_coded_directories(tmp_path: Path) -> None:
    """Regression for AHMCP-14-BR-03.

    A file matching the ``*task-plan*.md`` filename glob but living outside
    the four directories the old Makefile target hard-coded must still be
    swept by ``make lint-task-plans``. ``--scan-repo`` enumerates every
    tracked .md file via ``git ls-files`` and applies the same path filter
    the Claude Code hook uses.
    """
    _init_fake_repo(tmp_path)
    offending = (
        tmp_path
        / "packages"
        / "agent-orchestrator-mcp"
        / "docs"
        / "tech-debt"
        / "orchestrator-chat-tui-task-plan.md"
    )
    offending.parent.mkdir(parents=True)
    offending.write_text(
        "# Plan\n\n## Findings\n\n"
        "- AOMCP-3-BR-04: First.\n"
        "- AOMCP-3-BR-05: Second.\n"
        "- AOMCP-3-BR-06: Third.\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add bad plan", "-q")

    rc, _stdout, stderr = _run_hook_in(tmp_path, "--scan-repo")
    assert rc == 1, f"expected scan-repo to fail, got rc={rc}, stderr={stderr!r}"
    assert "orchestrator-chat-tui-task-plan.md" in stderr
    assert "AOMCP-3-BR-04" in stderr


def test_scan_repo_passes_on_clean_repo(tmp_path: Path) -> None:
    _init_fake_repo(tmp_path)
    plan = tmp_path / "docs" / "tasks" / "12.0" / "clean-task-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "# Plan\n\n## Slice 1\n- Implement foo\n- Test bar\n- Document baz\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add clean plan", "-q")

    rc, _stdout, stderr = _run_hook_in(tmp_path, "--scan-repo")
    assert rc == 0, f"expected scan-repo to pass, got rc={rc}, stderr={stderr!r}"
    assert stderr == ""


def test_scan_repo_ignores_unscoped_markdown(tmp_path: Path) -> None:
    """README.md and CLAUDE.md must remain exempt even with --scan-repo."""
    _init_fake_repo(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Repo\n\n"
        "- AOMCP-3-BR-04: noted\n"
        "- AOMCP-3-BR-05: noted\n"
        "- AOMCP-3-BR-06: noted\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "add readme", "-q")

    rc, _stdout, stderr = _run_hook_in(tmp_path, "--scan-repo")
    assert rc == 0, f"expected scan-repo to pass, got rc={rc}, stderr={stderr!r}"


def test_scan_repo_and_scan_paths_are_mutually_exclusive(tmp_path: Path) -> None:
    rc, _stdout, stderr = _run_hook_in(
        tmp_path, "--scan-repo", "--scan-paths", str(tmp_path)
    )
    assert rc != 0
    assert "mutually exclusive" in stderr


def test_hook_no_op_on_invalid_json() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input="not json at all",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0


def test_hook_no_op_on_missing_file_path() -> None:
    payload = {"tool_input": {"content": "irrelevant"}}
    rc, _ = _run_hook(payload)
    assert rc == 0
