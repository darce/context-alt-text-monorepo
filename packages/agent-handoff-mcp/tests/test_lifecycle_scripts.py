"""Shell-execution smoke tests for the lifecycle scripts.

These tests cover the **bash wrapper** layer of `scripts/task-start.sh`,
`scripts/task-finish.sh`, and `scripts/check-task-context.py` by running
the scripts via subprocess against a tmpdir-anchored fake monorepo.

Why this exists (AHMCP-18 item C): the package test suite exercises the
inline Python code via direct ``import`` (it cannot reach the bash
heredoc layer), and direct ``pytest`` invocations against the source do
not exercise the make targets either. As a result, three real bugs in
the lifecycle scripts shipped past CI in three consecutive sessions:

1. AHMCP-16 ``task-start.sh`` missing ``expected_revision`` (caught only
   when ``make task-start`` failed at the MCP registration step).
2. AHMCP-16-FU-01 ``task-finish.sh`` missing ``expected_revision``
   (same bug class, caught when ``make task-finish`` warned and silently
   left the archive snapshot in the wrong status).
3. AHMCP-17 apostrophe-in-heredoc bug (``the active row's revision``
   in a Python comment closed the bash single-quoted ``python -c``
   argument prematurely; caught only when ``make task-finish`` aborted
   with a bash syntax error from inside the python -c).

The fix for the bug class is detection: run the scripts end-to-end
inside a fixture so any future regression on the bash wrapper layer
fails a test instead of failing in production. Each test below is
designed to be cheap (single-commit tmp git repo, fork/exec a real
shell) and assertion-rich (exit code, archive row content,
context-check warnings).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_START_SCRIPT = REPO_ROOT / "scripts" / "task-start.sh"
TASK_FINISH_SCRIPT = REPO_ROOT / "scripts" / "task-finish.sh"
TASK_START_INLINE = REPO_ROOT / "scripts" / "_task_start_inline.py"
TASK_FINISH_INLINE = REPO_ROOT / "scripts" / "_task_finish_inline.py"
CHECK_CONTEXT_SCRIPT = REPO_ROOT / "scripts" / "check-task-context.py"
WORKTREE_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "worktree_audit.py"
WORKTREE_PRUNE_SCRIPT = REPO_ROOT / "scripts" / "worktree_prune.py"
TASK_PLAN_AUDIT_SCRIPT = REPO_ROOT / "scripts" / "task_plan_audit.py"
INTEGRITY_WATCHER_SCRIPT = REPO_ROOT / "scripts" / "integrity-watcher.sh"
GUARD_MAIN_BRANCH_HOOK = REPO_ROOT / "scripts" / "hooks" / "guard-main-branch.sh"
GUARD_MAIN_BRANCH_INLINE = REPO_ROOT / "scripts" / "hooks" / "_guard_main_branch_inline.py"
BRANCH_ISOLATION_GUARD = REPO_ROOT / "scripts" / "hooks" / "_branch_isolation_guard.py"
HARNESS_PROTOCOL_HELPER = REPO_ROOT / "scripts" / "hooks" / "_harness_protocol.py"
WORKTREE_DRIFT_HELPER = REPO_ROOT / "scripts" / "hooks" / "_worktree_drift.py"
WORKTREE_DRIFT_HOOK = REPO_ROOT / "scripts" / "hooks" / "guard-worktree-drift.sh"
CHECK_MAIN_CLEAN_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "check_main_clean.py"
POST_COMMIT_REFRESH_SHA = REPO_ROOT / "scripts" / "hooks" / "_post_commit_refresh_sha.py"
POST_COMMIT_HOOK = REPO_ROOT / "scripts" / "hooks" / "git" / "post-commit"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_fake_monorepo(tmp_path: Path) -> Path:
    """Create a tmp git repo that mimics the monorepo's lifecycle-script layout.

    Copies the lifecycle scripts and the agent-handoff-mcp package source
    into a temp directory so the inline Python in the scripts has a
    real PYTHONPATH to import from. The git history is a single commit
    on ``main`` so ``git rev-parse HEAD`` works.
    """
    repo = tmp_path / "fake-monorepo"
    repo.mkdir()

    # Copy lifecycle scripts. AHMCP-20 promoted the inline Python out of
    # task-start.sh and task-finish.sh into _task_start_inline.py and
    # _task_finish_inline.py respectively, so the fake monorepo must
    # carry both the bash wrapper and the standalone Python module for
    # each entry point.
    (repo / "scripts").mkdir()
    shutil.copy2(TASK_START_SCRIPT, repo / "scripts" / "task-start.sh")
    shutil.copy2(TASK_FINISH_SCRIPT, repo / "scripts" / "task-finish.sh")
    shutil.copy2(TASK_START_INLINE, repo / "scripts" / "_task_start_inline.py")
    shutil.copy2(TASK_FINISH_INLINE, repo / "scripts" / "_task_finish_inline.py")
    shutil.copy2(CHECK_CONTEXT_SCRIPT, repo / "scripts" / "check-task-context.py")
    if WORKTREE_AUDIT_SCRIPT.exists():
        shutil.copy2(WORKTREE_AUDIT_SCRIPT, repo / "scripts" / "worktree_audit.py")
    if WORKTREE_PRUNE_SCRIPT.exists():
        shutil.copy2(WORKTREE_PRUNE_SCRIPT, repo / "scripts" / "worktree_prune.py")
    if TASK_PLAN_AUDIT_SCRIPT.exists():
        shutil.copy2(TASK_PLAN_AUDIT_SCRIPT, repo / "scripts" / "task_plan_audit.py")
    os.chmod(repo / "scripts" / "task-start.sh", 0o755)
    os.chmod(repo / "scripts" / "task-finish.sh", 0o755)
    os.chmod(repo / "scripts" / "_task_start_inline.py", 0o755)
    os.chmod(repo / "scripts" / "_task_finish_inline.py", 0o755)
    os.chmod(repo / "scripts" / "check-task-context.py", 0o755)
    if (repo / "scripts" / "worktree_audit.py").exists():
        os.chmod(repo / "scripts" / "worktree_audit.py", 0o755)
    if (repo / "scripts" / "worktree_prune.py").exists():
        os.chmod(repo / "scripts" / "worktree_prune.py", 0o755)
    if (repo / "scripts" / "task_plan_audit.py").exists():
        os.chmod(repo / "scripts" / "task_plan_audit.py", 0o755)
    if GUARD_MAIN_BRANCH_HOOK.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(GUARD_MAIN_BRANCH_HOOK, repo / "scripts" / "hooks" / "guard-main-branch.sh")
        os.chmod(repo / "scripts" / "hooks" / "guard-main-branch.sh", 0o755)
    if GUARD_MAIN_BRANCH_INLINE.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(GUARD_MAIN_BRANCH_INLINE, repo / "scripts" / "hooks" / "_guard_main_branch_inline.py")
    if BRANCH_ISOLATION_GUARD.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(BRANCH_ISOLATION_GUARD, repo / "scripts" / "hooks" / "_branch_isolation_guard.py")
    if CHECK_MAIN_CLEAN_SCRIPT.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(CHECK_MAIN_CLEAN_SCRIPT, repo / "scripts" / "hooks" / "check_main_clean.py")
    if HARNESS_PROTOCOL_HELPER.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(HARNESS_PROTOCOL_HELPER, repo / "scripts" / "hooks" / "_harness_protocol.py")
    if POST_COMMIT_REFRESH_SHA.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(POST_COMMIT_REFRESH_SHA, repo / "scripts" / "hooks" / "_post_commit_refresh_sha.py")
    if WORKTREE_DRIFT_HELPER.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(WORKTREE_DRIFT_HELPER, repo / "scripts" / "hooks" / "_worktree_drift.py")
    if POST_COMMIT_HOOK.exists():
        (repo / "scripts" / "hooks" / "git").mkdir(parents=True, exist_ok=True)
        shutil.copy2(POST_COMMIT_HOOK, repo / "scripts" / "hooks" / "git" / "post-commit")
        os.chmod(repo / "scripts" / "hooks" / "git" / "post-commit", 0o755)
    if WORKTREE_DRIFT_HOOK.exists():
        (repo / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
        shutil.copy2(WORKTREE_DRIFT_HOOK, repo / "scripts" / "hooks" / "guard-worktree-drift.sh")
        os.chmod(repo / "scripts" / "hooks" / "guard-worktree-drift.sh", 0o755)
    (repo / "docs" / "agentic" / "contracts").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agentic" / "contracts" / "harness-protocol.yaml").write_text(
        """version: 1

branch_isolation:
  protected_branches:
    - main
    - master
  code_roots:
    - apps/
    - packages/
    - scripts/
    - .github/hooks/
    - .claude/
    - mk/
  protected_extensions:
    - .py
    - .ts
    - .tsx
    - .js
    - .jsx
    - .php
    - .sql
    - .sh
    - .css
    - .scss
    - .mk
  root_protected_files:
    - Makefile
  permitted_main_surfaces:
    - pattern: "docs/tasks/**/*.md"
      reason: "Task plans"
  enforcers:
    - path: .github/hooks/guard-main-branch.py
      harness: vscode
    - path: scripts/hooks/guard-main-branch.sh
      harness: claude
""",
        encoding="utf-8",
    )

    # Copy the agent-handoff-mcp source so the inline Python can import it.
    package_src = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src"
    target_pkg = repo / "packages" / "agent-handoff-mcp" / "src"
    target_pkg.parent.mkdir(parents=True)
    shutil.copytree(package_src, target_pkg)

    # Initialise the git repo.
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _make_env(repo: Path) -> dict[str, str]:
    """Build the env passed to the lifecycle scripts.

    The scripts compose their python interpreter path as
    ``${PYENV_ROOT}/versions/${PYENV_VERSION}/bin/python``. To run them
    under whichever python is running the tests (whose site-packages
    has all the dependencies including ``fastmcp``), we create a tmp
    pyenv-shim directory containing a small wrapper shell script that
    ``exec``\\s ``sys.executable``. A bare symlink does not work on
    every platform because some pyenv interpreters resolve their
    ``prefix`` from the symlink path rather than the resolved real path,
    which then misses the venv's site-packages.
    """
    env = os.environ.copy()
    # Fake-repo lifecycle tests must not inherit caller git / handoff routing.
    # Pytest and editor integrations can leak these vars from the real repo,
    # which makes hook subprocesses resolve the wrong checkout or DB.
    for key in (
        "AGENT_HANDOFF_WORKSPACE_ROOT",
        "AGENT_HANDOFF_STATE_DIR",
        "AGENT_HANDOFF_CURRENT_TASK_PATH",
        "AGENT_HANDOFF_DASHBOARD_PATH",
        "AGENT_HANDOFF_EXPORTS_DIR",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_WORK_TREE",
    ):
        env.pop(key, None)
    # Ensure the inline python -c invocation can find agent_handoff_mcp
    # by pointing at the fake monorepo's package source. The test
    # suite's `LOCAL_PYTHONPATH` is irrelevant inside the subprocess.
    env["PYTHONPATH"] = str(repo / "packages" / "agent-handoff-mcp" / "src")
    pyenv_shim = repo / ".pyenv-shim"
    pyenv_version = env.get("PYENV_VERSION", "description-service")
    bin_dir = pyenv_shim / "versions" / pyenv_version / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    python_wrapper = bin_dir / "python"
    if python_wrapper.exists() or python_wrapper.is_symlink():
        python_wrapper.unlink()
    python_wrapper.write_text(f'#!/bin/bash\nexec "{sys.executable}" "$@"\n')
    python_wrapper.chmod(0o755)
    env["PYENV_ROOT"] = str(pyenv_shim)
    env["PYENV_VERSION"] = pyenv_version
    # Forward the test-suite SHA validation bypass so the lifecycle
    # scripts running in this fake monorepo do not require a real git
    # commit object for every commit_sha they record.
    env["AGENT_HANDOFF_SKIP_SHA_VALIDATION"] = "1"
    return env


def _run_script(
    script: str,
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cwd / "scripts" / script), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def _install_agent_handoff_cli_stub(repo: Path, payload: str) -> Path:
    """Install an `agent-handoff-mcp` CLI stub that prints the given JSON payload."""

    bin_dir = repo / ".test-bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "agent-handoff-mcp"
    stub.write_text(f"#!/bin/bash\ncat <<'EOF'\n{payload}\nEOF\n")
    stub.chmod(0o755)
    return bin_dir


def _make_path_without_handoff_cli(repo: Path) -> str:
    """Build a minimal PATH that keeps shell/git/python but omits agent-handoff-mcp."""

    bin_dir = repo / ".test-bin-no-handoff"
    bin_dir.mkdir(exist_ok=True)
    for name in ("bash", "git", "python3", "cat"):
        source = shutil.which(name)
        if source is None:
            raise AssertionError(f"required test binary {name!r} was not found on PATH")
        target = bin_dir / name
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(source)
    return str(bin_dir)


def _read_active_row(repo: Path) -> dict[str, object] | None:
    db_path = repo / ".task-state" / "handoff.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM handoff_state ORDER BY datetime(updated_at) DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def _read_archive_row(repo: Path, task_ref: str) -> dict[str, object] | None:
    db_path = repo / ".task-state" / "handoff.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM task_archives WHERE task_ref = ?", (task_ref,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# task-start.sh smoke tests
# ---------------------------------------------------------------------------


def test_task_start_succeeds_on_cold_start(tmp_path: Path) -> None:
    """task-start.sh should succeed on a virgin handoff DB.

    This is the cold-start path: handoff_state.id=1 does not yet exist,
    so set_handoff_state inserts a new row and the inline Python should
    not need an expected_revision."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    proc = _run_script("task-start.sh", repo, "TS-COLD-1", "Cold-start objective", env=env)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK rev=0" in proc.stdout, proc.stdout
    assert "MCP registration skipped" not in proc.stdout
    active = _read_active_row(repo)
    assert active is not None
    assert active["task_ref"] == "TS-COLD-1"
    assert active["status"] == "in_progress"


def test_task_start_succeeds_when_existing_active_task_present(tmp_path: Path) -> None:
    """AHMCP-16 regression: task-start.sh must succeed when handoff_state.id=1
    already exists. Before the fix, the second invocation failed with
    `expected_revision is required for updates`."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    first = _run_script("task-start.sh", repo, "TS-EXISTING-1", "First task", env=env)
    assert first.returncode == 0, f"stdout={first.stdout!r} stderr={first.stderr!r}"

    # The first task-start created the row at rev=0. The second must
    # transparently fetch the revision and update.
    second = _run_script("task-start.sh", repo, "TS-EXISTING-2", "Second task", env=env)
    assert second.returncode == 0, f"stdout={second.stdout!r} stderr={second.stderr!r}"
    assert "MCP registration skipped" not in second.stdout
    assert "MCP registration skipped" not in second.stderr

    active = _read_active_row(repo)
    assert active is not None
    assert active["task_ref"] == "TS-EXISTING-2"
    assert int(active["revision"]) >= 1  # rev incremented from cold-start 0


def test_task_start_archives_previous_task_for_dashboard_status(tmp_path: Path) -> None:
    """E17-11: task-start leaves the outgoing task's row in place (multi-active).

    The greenfield multi-active-task model does not auto-archive outgoing
    tasks; both coexist as live handoff_state rows and the dashboard shows
    each one's live status.
    """
    from agent_handoff_mcp import RuntimeConfig, configure_runtime, generate_dashboard_md

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    first = _run_script("task-start.sh", repo, "TS-DASH-1", "First task", env=env)
    assert first.returncode == 0, f"stdout={first.stdout!r} stderr={first.stderr!r}"

    second = _run_script("task-start.sh", repo, "TS-DASH-2", "Second task", env=env)
    assert second.returncode == 0, f"stdout={second.stdout!r} stderr={second.stderr!r}"

    runtime = RuntimeConfig.for_repo(repo)
    configure_runtime(runtime)
    dashboard = generate_dashboard_md(write_file=False)
    assert dashboard["ok"] is True
    assert "TS-DASH-1" in dashboard["markdown"]
    assert "TS-DASH-2" in dashboard["markdown"]
    assert "in_progress" in dashboard["markdown"]


# ---------------------------------------------------------------------------
# task-finish.sh smoke tests
# ---------------------------------------------------------------------------


def test_task_finish_archives_active_task_with_status_done(tmp_path: Path) -> None:
    """AHMCP-16-FU-01 regression: task-finish.sh must successfully update the
    active task to status='done' before archiving. Before the fix, the
    update_task_status call was rejected with `expected_revision is
    required` and the archive snapshot was captured with the old status."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    # Bootstrap a task and create the matching feature branch (task-finish
    # expects the branch to exist and be merged into main).
    started = _run_script("task-start.sh", repo, "TF-DONE-1", "Finish me", env=env)
    assert started.returncode == 0, started.stderr

    # Simulate the merge: the feature branch is reachable from main.
    # task-start created `feature/tf-done-1`. We merge it back into main
    # by fast-forward (no real changes — the branch is just at HEAD).
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-done-1")

    finished = _run_script("task-finish.sh", repo, "TF-DONE-1", env=env)
    assert finished.returncode == 0, f"stdout={finished.stdout!r} stderr={finished.stderr!r}"
    assert "expected_revision is required" not in finished.stderr
    assert "syntax error" not in finished.stderr
    assert "Task TF-DONE-1 finished" in finished.stdout

    archived = _read_archive_row(repo, "TF-DONE-1")
    assert archived is not None
    snapshot = json.loads(archived["snapshot_json"])
    assert snapshot["active"]["status"] == "done", (
        f"task-finish must capture status=done in archive snapshot, got {snapshot['active']['status']!r}"
    )


def test_task_finish_archives_non_active_task_with_status_done(tmp_path: Path) -> None:
    """task-finish.sh must resolve the finished task's revision, not the current active task.

    Regression for the post-merge MAINT-AHMCP-QUALITY-20260417 review:
    finishing a task from the root worktree while another task is active
    must still archive the finished task with status='done'.
    """
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "TF-DONE-OTHER-1", "Finish me later", env=env)
    assert started.returncode == 0, started.stderr

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-done-other-1")

    other = _run_script("task-start.sh", repo, "TF-DONE-OTHER-2", "Stay active", env=env)
    assert other.returncode == 0, other.stderr

    finished = _run_script("task-finish.sh", repo, "TF-DONE-OTHER-1", env=env)
    assert finished.returncode == 0, f"stdout={finished.stdout!r} stderr={finished.stderr!r}"
    assert "expected_revision is required" not in finished.stderr

    archived = _read_archive_row(repo, "TF-DONE-OTHER-1")
    assert archived is not None
    snapshot = json.loads(archived["snapshot_json"])
    assert snapshot["active"]["status"] == "done", (
        "task-finish must capture status=done for the target task even when another task is active"
    )


def test_task_lifecycle_scripts_have_no_multiline_python_heredoc() -> None:
    """AHMCP-20 / Layer 1 of the heredoc-eradication bug class fix.

    This is the structural successor to the AHMCP-17 apostrophe-static-
    check tests (which used to walk the heredoc body and assert no `'`
    characters appeared inside it). The new assertion is stronger:
    instead of checking that the heredoc body is apostrophe-free, we
    assert the heredoc itself does not exist. The inline Python lives
    at scripts/_task_start_inline.py and scripts/_task_finish_inline.py
    instead, and bash quoting is no longer in the loop.
    """
    for script in (TASK_START_SCRIPT, TASK_FINISH_SCRIPT):
        text = script.read_text()
        # The forbidden pattern is `python -c '<multiline body>'`. We look
        # for `python` followed by `-c '` and check whether the next `'`
        # is on the same line. Any cross-line `-c '...'` is the bug class.
        cursor = 0
        while True:
            idx = text.find(" -c '", cursor)
            if idx == -1:
                break
            close_quote = text.find("'", idx + 5)
            assert close_quote != -1, f"{script.name}: unterminated `-c '...'` starting at offset {idx}"
            body = text[idx + 5 : close_quote]
            assert "\n" not in body, (
                f"{script.name}: multi-line `python -c '...'` heredoc detected at offset {idx} "
                f"({body.count(chr(10)) + 1} lines). AHMCP-20 forbids this pattern. Promote the "
                f"inline Python to a standalone .py file and invoke it via `python <script.py>`. "
                f"See scripts/_task_start_inline.py for the canonical example."
            )
            cursor = close_quote + 1


def test_handoff_make_targets_use_render_handoff_current_task() -> None:
    """slice-start/task must not call the removed CLI `task` subcommand."""

    handoff_makefile = (REPO_ROOT / "mk" / "handoff.mk").read_text()

    assert "render-handoff --kind current_task" in handoff_makefile
    assert "$(MCP_CMD) $(MCP_STATE_ARGS) task" not in handoff_makefile
    assert 'task "$(TASK)"' not in handoff_makefile


def test_lint_no_inline_python_heredoc_passes_on_current_scripts_tree() -> None:
    """AHMCP-20 / Layer 3 of the heredoc-eradication bug class fix.

    The lint guard at scripts/hooks/lint-no-inline-python-heredoc.py is
    the long-term defense against future heredocs sneaking back in. This
    test asserts the guard passes on the current scripts/ tree, which is
    the per-PR regression check. If the guard ever fails because someone
    re-introduced a heredoc, this test fails the package suite and the
    pre-merge gate refuses the merge.
    """
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-no-inline-python-heredoc.py"
    assert lint_script.exists(), f"missing lint guard at {lint_script}"
    proc = subprocess.run(
        [sys.executable, str(lint_script)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"lint-no-inline-python-heredoc failed on the current scripts/ tree:\n{proc.stderr}"


def test_lint_no_inline_python_heredoc_catches_synthetic_violation(tmp_path: Path) -> None:
    """AHMCP-20 / Layer 3 negative test: feed the guard a synthetic
    multi-line `python -c '...'` heredoc and assert it returns exit
    code 1 with a clear message naming the offending file and line."""
    fixture_dir = tmp_path / "fixture-scripts"
    fixture_dir.mkdir()
    bad_script = fixture_dir / "bad.sh"
    bad_script.write_text("#!/usr/bin/env bash\npython -c '\nimport os\nprint(\"hello\")\n'\n")
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-no-inline-python-heredoc.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(fixture_dir / "*.sh")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        f"lint guard should fail on a multi-line heredoc fixture; got exit={proc.returncode} stderr={proc.stderr!r}"
    )
    assert "multi-line `python -c '...'` heredoc" in proc.stderr
    assert "bad.sh" in proc.stderr


def test_lint_no_inline_python_heredoc_allows_single_line_invocation(tmp_path: Path) -> None:
    """AHMCP-20 / Layer 3 escape hatch: a single-line `python -c "..."`
    invocation is allowed because it cannot embed multi-line content
    and the apostrophe risk is minimal. The guard is only after the
    multi-line heredoc class."""
    fixture_dir = tmp_path / "fixture-scripts"
    fixture_dir.mkdir()
    ok_script = fixture_dir / "ok.sh"
    ok_script.write_text('#!/usr/bin/env bash\npython -c "import sys; print(sys.version)"\n')
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-no-inline-python-heredoc.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(fixture_dir / "*.sh")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"lint guard should allow single-line `python -c '...'`; got exit={proc.returncode} stderr={proc.stderr!r}"
    )


# ---------------------------------------------------------------------------
# task-finish.sh integrity guard (AHMCP-18 item B)
# ---------------------------------------------------------------------------


def test_task_finish_aborts_when_working_tree_drifted_from_head(tmp_path: Path) -> None:
    """AHMCP-18 item B: task-finish.sh must refuse to archive when a tracked
    file in the working tree disagrees with HEAD content. This catches the
    AHMCP-15-BR-FIXES api.py-revert incident class."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "TF-DRIFT-1", "Drift guard repro", env=env)
    assert started.returncode == 0, started.stderr
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-drift-1")

    # Tamper with a tracked file so it disagrees with HEAD.
    tracked = repo / "scripts" / "task-finish.sh"
    original = tracked.read_text()
    tracked.write_text(original + "\n# tampered post-merge\n")

    finished = _run_script("task-finish.sh", repo, "TF-DRIFT-1", env=env)
    assert finished.returncode == 4, (
        f"task-finish must exit 4 on integrity violation; "
        f"got {finished.returncode}\nstdout={finished.stdout!r}\nstderr={finished.stderr!r}"
    )
    assert "Working tree disagrees with HEAD" in finished.stderr
    assert "scripts/task-finish.sh" in finished.stderr

    # The archive must NOT have been written when the integrity check fails.
    archived = _read_archive_row(repo, "TF-DRIFT-1")
    assert archived is None, (
        f"task-finish must abort BEFORE archiving when integrity check fails; found archive row: {archived}"
    )


def test_task_finish_allows_drift_listed_in_dirty_allowlist(tmp_path: Path) -> None:
    """AHMCP-18 item B escape hatch: paths listed in
    .task-state/dirty-allowlist are treated as expected drift and the
    integrity check passes."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "TF-ALLOW-1", "Allowlist repro", env=env)
    assert started.returncode == 0, started.stderr
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-allow-1")

    # Tamper with a tracked file.
    tracked = repo / "scripts" / "task-finish.sh"
    tracked.write_text(tracked.read_text() + "\n# intentional drift\n")

    # Add it to the allowlist.
    allowlist = repo / ".task-state" / "dirty-allowlist"
    allowlist.parent.mkdir(parents=True, exist_ok=True)
    allowlist.write_text("# AHMCP-18 test allowlist\nscripts/task-finish.sh\n")

    finished = _run_script("task-finish.sh", repo, "TF-ALLOW-1", env=env)
    assert finished.returncode == 0, (
        f"task-finish should pass when drift is allowlisted; got {finished.returncode}\nstderr={finished.stderr!r}"
    )

    archived = _read_archive_row(repo, "TF-ALLOW-1")
    assert archived is not None, "task-finish should archive after passing integrity check"


# ---------------------------------------------------------------------------
# check-task-context.py smoke tests (AHMCP-18 items A + done-warning)
# ---------------------------------------------------------------------------


def test_check_task_context_warns_on_unexpected_dirty_paths(tmp_path: Path) -> None:
    """AHMCP-18 item A: check-task-context.py should print an integrity
    warning when tracked-but-modified files are not in the dirty-allowlist."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "CHECK-DIRTY-1", "Dirty repro", env=env)
    assert started.returncode == 0, started.stderr

    # Tamper with a tracked file.
    tracked = repo / "scripts" / "task-finish.sh"
    tracked.write_text(tracked.read_text() + "\n# unexpected drift\n")

    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check-task-context.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "Working-tree integrity" in proc.stdout, proc.stdout
    assert "scripts/task-finish.sh" in proc.stdout, proc.stdout


def test_check_task_context_silent_when_drift_is_allowlisted(tmp_path: Path) -> None:
    """AHMCP-18 item A escape hatch: drift in the allowlist must not warn."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "CHECK-ALLOW-1", "Allowlist repro", env=env)
    assert started.returncode == 0, started.stderr

    tracked = repo / "scripts" / "task-finish.sh"
    tracked.write_text(tracked.read_text() + "\n# intentional drift\n")

    allowlist = repo / ".task-state" / "dirty-allowlist"
    allowlist.parent.mkdir(parents=True, exist_ok=True)
    allowlist.write_text("scripts/task-finish.sh\n")

    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check-task-context.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "Working-tree integrity" not in proc.stdout, proc.stdout


def test_check_task_context_returns_zero_on_drift(tmp_path: Path) -> None:
    """E17-4 Slice 5: drift should warn without failing the caller."""
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "CHECK-DRIFT-1", "Drift exit repro", env=env)
    assert started.returncode == 0, started.stderr

    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check-task-context.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"check-task-context must exit 0 on drift; got {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "Drift detected" in proc.stdout, proc.stdout


def test_check_task_context_reports_dirty_main_without_active_task(tmp_path: Path) -> None:
    """E17-4 Slice 2: dirty main with no task should print the maintenance-task hint."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    tracked = repo / "scripts" / "check-task-context.py"
    tracked.write_text(tracked.read_text() + "\n# dirty main repro\n")

    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "check-task-context.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "check-task-context should keep dirty-main warnings non-fatal when there is no active task; "
        f"got {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "No active handoff task. Nothing to check." in proc.stdout, proc.stdout
    assert "Working-tree integrity" in proc.stdout, proc.stdout
    assert "Register a maintenance task before continuing with main-branch edits" in proc.stdout, proc.stdout


def test_guard_main_branch_warns_without_active_task(tmp_path: Path) -> None:
    """E17-4 Slice 2: permitted main edits should warn when no task is registered."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    stub_dir = _install_agent_handoff_cli_stub(repo, '{"data":{"active":null}}')
    env["PATH"] = f"{stub_dir}:{env['PATH']}"

    payload = json.dumps({"tool_input": {"file_path": str(repo / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-main-branch.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "Editing on main without an active handoff task" in proc.stderr, proc.stderr
    assert "set_handoff_state(task_ref='MAINT-<slug>'" in proc.stderr, proc.stderr


def test_guard_main_branch_is_silent_with_active_task(tmp_path: Path) -> None:
    """E17-4 Slice 2: the warning should disappear once a task is active."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    stub_dir = _install_agent_handoff_cli_stub(repo, '{"data":{"active":{"task_ref":"MAINT-test"}}}')
    env["PATH"] = f"{stub_dir}:{env['PATH']}"

    payload = json.dumps({"tool_input": {"file_path": str(repo / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-main-branch.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "Editing on main without an active handoff task" not in proc.stderr, proc.stderr


def test_guard_main_branch_blocks_scripts_code_path_on_main(tmp_path: Path) -> None:
    """E17-8 Slice 1: script code paths are now protected by the contract."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    payload = json.dumps({"tool_input": {"file_path": str(repo / "scripts" / "check-task-context.py")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-main-branch.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "Protected edits are not allowed on the main branch" in proc.stderr, proc.stderr
    assert "scripts/check-task-context.py" in proc.stderr, proc.stderr


def test_guard_worktree_drift_blocks_when_edit_targets_root_worktree(tmp_path: Path) -> None:
    """E17-8 Slice 2: wrong-worktree edits should block by default."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["CLAUDE_PROJECT_DIR"] = str(repo)

    started = _run_script("task-start.sh", repo, "DRIFT-ASK-1", "Drift prompt repro", env=env)
    assert started.returncode == 0, started.stderr

    payload = json.dumps({"tool_input": {"file_path": str(repo / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-worktree-drift.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    parsed = json.loads(proc.stdout)
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "block"
    assert "WorkspaceRootDrift" in hook_output["permissionDecisionReason"]


def test_guard_worktree_drift_allows_target_worktree_edits(tmp_path: Path) -> None:
    """E17-8 Slice 2: edits in the registered task worktree pass silently."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["CLAUDE_PROJECT_DIR"] = str(repo)

    started = _run_script("task-start.sh", repo, "DRIFT-ASK-2", "Same worktree repro", env=env)
    assert started.returncode == 0, started.stderr

    task_worktree = repo.parent / "context-alt-text-monorepo-drift-ask-2"
    payload = json.dumps({"tool_input": {"file_path": str(task_worktree / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-worktree-drift.sh")],
        cwd=task_worktree,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == ""


def test_guard_worktree_drift_allows_allowlisted_main_surface(tmp_path: Path) -> None:
    """E17-8 Slice 2: allow-listed task-plan edits on main pass silently."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["CLAUDE_PROJECT_DIR"] = str(repo)

    started = _run_script("task-start.sh", repo, "DRIFT-ALLOW-1", "Allow-list repro", env=env)
    assert started.returncode == 0, started.stderr

    payload = json.dumps({"tool_input": {"file_path": str(repo / "docs" / "tasks" / "17.0" / "plan.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-worktree-drift.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == ""


def test_guard_worktree_drift_blocks_when_active_task_context_is_unresolved(tmp_path: Path) -> None:
    """E17-11 Slice 4: ambiguous workspace state must fail closed."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["CLAUDE_PROJECT_DIR"] = str(repo)

    started = _run_script("task-start.sh", repo, "DRIFT-UNRESOLVED-1", "Unresolved context repro", env=env)
    assert started.returncode == 0, started.stderr

    db_path = repo / ".task-state" / "handoff.db"
    other_worktree = repo.parent / "context-alt-text-monorepo-drift-unresolved-2"
    other_worktree.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO handoff_state (
                id, task_ref, objective, focus, status, target_branch,
                target_worktree_path, revision, updated_at, updated_by,
                updated_branch, updated_commit_sha
            ) VALUES (?, ?, ?, ?, 'in_progress', ?, ?, 0,
                      datetime('now'), 'tester', ?, ?)
            """,
            (
                None,
                "DRIFT-UNRESOLVED-2",
                "Second unresolved task",
                None,
                "feature/drift-unresolved-2",
                str(other_worktree),
                "feature/drift-unresolved-2",
                "abc123",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    payload = json.dumps({"tool_input": {"file_path": str(repo / "scripts" / "check-task-context.py")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-worktree-drift.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    parsed = json.loads(proc.stdout)
    hook_output = parsed["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "block"
    assert "UnresolvedTaskContextError" in hook_output["permissionDecisionReason"]
    assert "Ambiguous active task" in hook_output["permissionDecisionReason"]


def test_guard_worktree_drift_allows_env_bypass(tmp_path: Path) -> None:
    """E17-8 Slice 2: ALT_ALLOW_WORKTREE_DRIFT downgrades the block."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["ALT_ALLOW_WORKTREE_DRIFT"] = "1"

    started = _run_script("task-start.sh", repo, "DRIFT-ALLOW-2", "Env bypass repro", env=env)
    assert started.returncode == 0, started.stderr

    payload = json.dumps({"tool_input": {"file_path": str(repo / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-worktree-drift.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout.strip() == ""


def test_guard_main_branch_skips_warning_when_cli_is_unavailable(tmp_path: Path) -> None:
    """E17-4 Slice 2: missing CLI should not masquerade as 'no active task'."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    env["PATH"] = _make_path_without_handoff_cli(repo)

    payload = json.dumps({"tool_input": {"file_path": str(repo / "README.md")}})
    proc = subprocess.run(
        [str(repo / "scripts" / "hooks" / "guard-main-branch.sh")],
        cwd=repo,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "Editing on main without an active handoff task" not in proc.stderr, proc.stderr


def test_worktree_audit_uses_archived_snapshot_target_branch(tmp_path: Path) -> None:
    """E17-4 Slice 1: archived snapshot target_branch registers a branch.

    `archived_branch` stores archive provenance (often `main` at task-finish),
    so the audit must consult the archived snapshot's active.target_branch
    instead when deciding whether a local branch belongs to a known task.
    """
    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "WA-SNAPSHOT-1", "Snapshot audit repro", env=env)
    assert started.returncode == 0, started.stderr

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/wa-snapshot-1")

    finished = _run_script("task-finish.sh", repo, "WA-SNAPSHOT-1", env=env)
    assert finished.returncode == 0, finished.stderr

    _git(repo, "branch", "feature/wa-snapshot-1", "main")

    audit_script = repo / "scripts" / "worktree_audit.py"
    assert audit_script.exists(), "worktree_audit.py must exist in the scripts tree"
    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "worktree_audit should treat archived snapshot target_branch as registered; "
        f"got exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_worktree_audit_reports_orphan_branch(tmp_path: Path) -> None:
    """E17-4 Slice 1: orphan branches should fail the audit with a branch list."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    _git(repo, "branch", "feature/wp-orphan-2", "main")

    audit_script = repo / "scripts" / "worktree_audit.py"
    assert audit_script.exists(), "worktree_audit.py must exist in the scripts tree"
    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        "worktree_audit should fail when an orphan branch exists; "
        f"got exit={proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert "feature/wp-orphan-2" in proc.stdout, proc.stdout
    assert "orphan local branches detected" in proc.stdout, proc.stdout


def test_worktree_prune_deletes_orphans_and_keeps_registered_branches(tmp_path: Path) -> None:
    """E17-4 stretch: worktree-prune should delete only orphan branches."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "WP-KEEP-1", "Keep registered branch", env=env)
    assert started.returncode == 0, started.stderr

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/wp-keep-1")
    finished = _run_script("task-finish.sh", repo, "WP-KEEP-1", env=env)
    assert finished.returncode == 0, finished.stderr
    _git(repo, "branch", "feature/wp-keep-1", "main")

    _git(repo, "branch", "feature/wp-orphan-1", "main")

    prune_script = repo / "scripts" / "worktree_prune.py"
    assert prune_script.exists(), "worktree_prune.py must exist in the scripts tree"
    proc = subprocess.run(
        [sys.executable, str(prune_script), "--yes"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"

    branches = _git(repo, "branch", "--list", "feature/wp-*").stdout
    assert "feature/wp-orphan-1" not in branches, branches
    assert "feature/wp-keep-1" in branches, branches


def test_worktree_prune_dry_run_preserves_orphans(tmp_path: Path) -> None:
    """E17-4 BR-11: dry-run should preview deletions without mutating branches."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    _git(repo, "branch", "feature/wp-preview-1", "main")

    prune_script = repo / "scripts" / "worktree_prune.py"
    assert prune_script.exists(), "worktree_prune.py must exist in the scripts tree"
    proc = subprocess.run(
        [sys.executable, str(prune_script), "--dry-run"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert "Dry run: would delete with `git branch -d`." in proc.stdout, proc.stdout
    assert "previewed=1" in proc.stdout, proc.stdout

    branches = _git(repo, "branch", "--list", "feature/wp-preview-1").stdout
    assert "feature/wp-preview-1" in branches, branches


def test_task_plan_audit_reports_missing_then_passes_with_plan(tmp_path: Path) -> None:
    """E17-4 Slice 6: tagged commits without a plan file must fail the audit."""
    repo = _build_fake_monorepo(tmp_path)

    audit_script = repo / "scripts" / "task_plan_audit.py"
    assert audit_script.exists(), "task_plan_audit.py must exist in the scripts tree"

    _git(repo, "commit", "--allow-empty", "-q", "-m", "feat(AHMCP-31): add touched files")

    missing = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert missing.returncode == 1, (
        f"task_plan_audit should fail when the tagged task has no plan file; got {missing.returncode}"
    )
    assert "AHMCP-31" in missing.stdout, missing.stdout

    plan_dir = repo / "packages" / "agent-handoff-mcp" / "docs" / "tasks"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "AHMCP-31-touched-files-task-plan.md").write_text("# AHMCP-31\n")

    clean = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert clean.returncode == 0, (
        f"task_plan_audit should pass once the tagged task has a plan file; got {clean.returncode}"
    )


def test_task_plan_audit_ignores_non_task_rule_tags(tmp_path: Path) -> None:
    """E17-4 Slice 6: repo rule tags like RG-018 are not task refs."""
    repo = _build_fake_monorepo(tmp_path)

    audit_script = repo / "scripts" / "task_plan_audit.py"
    assert audit_script.exists(), "task_plan_audit.py must exist in the scripts tree"

    _git(repo, "commit", "--allow-empty", "-q", "-m", "docs(RG-018): document raw sqlite3 ban")

    proc = subprocess.run(
        [sys.executable, str(audit_script)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "task_plan_audit should ignore non-task rule tags like RG-018; "
        f"got {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


def test_task_finish_inline_warns_when_target_branch_still_exists(tmp_path: Path) -> None:
    """E17-4 Slice 3: archive should warn when the feature branch still exists."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "TF-BRANCH-1", "Branch persistence repro", env=env)
    assert started.returncode == 0, started.stderr

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-branch-1")

    inline_env = env | {"REPO_ROOT": str(repo), "TASK": "TF-BRANCH-1"}
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "_task_finish_inline.py")],
        cwd=repo,
        env=inline_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "still exists after archive" in proc.stderr, proc.stderr


def test_task_finish_normal_path_does_not_warn_about_deleted_branch(tmp_path: Path) -> None:
    """E17-4 Slice 3: normal task-finish should stay quiet after branch deletion."""

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    started = _run_script("task-start.sh", repo, "TF-NO-WARN-1", "Normal finish repro", env=env)
    assert started.returncode == 0, started.stderr

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--ff-only", "feature/tf-no-warn-1")

    finished = _run_script("task-finish.sh", repo, "TF-NO-WARN-1", env=env)
    assert finished.returncode == 0, finished.stderr
    assert "still exists after archive" not in finished.stderr, finished.stderr


def test_post_commit_refresh_helper_updates_active_task_commit_sha(tmp_path: Path) -> None:
    """The helper subprocess should stamp HEAD onto the active task row."""

    from agent_handoff_mcp import RuntimeConfig, configure_runtime, set_handoff_state

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)
    configure_runtime(RuntimeConfig.for_repo(repo))

    seeded = set_handoff_state(
        task_ref="PC-HOOK-1",
        objective="Refresh commit SHA after commit",
        status="in_progress",
        target_branch="feature/pc-hook-1",
    )
    assert seeded["ok"] is True, seeded

    _git(repo, "checkout", "-q", "-b", "feature/pc-hook-1")

    touched = repo / "post-commit.txt"
    touched.write_text("hook smoke test\n", encoding="utf-8")
    _git(repo, "add", "post-commit.txt")
    commit = subprocess.run(
        ["git", "commit", "-q", "-m", "exercise post-commit hook"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert commit.returncode == 0, commit.stderr

    helper = subprocess.run(
        [env["PYENV_ROOT"] + f"/versions/{env['PYENV_VERSION']}/bin/python", str(repo / "scripts" / "hooks" / "_post_commit_refresh_sha.py")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert helper.returncode == 0, helper.stderr

    head_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    with sqlite3.connect(repo / ".task-state" / "handoff.db") as conn:
        row = conn.execute(
            "SELECT revision, updated_branch, updated_commit_sha FROM handoff_state WHERE task_ref = ?",
            ("PC-HOOK-1",),
        ).fetchone()

    assert row is not None
    revision, updated_branch, updated_commit_sha = row
    assert updated_commit_sha == head_sha
    assert updated_branch == "feature/pc-hook-1"
    assert revision == 1


def test_post_commit_hook_has_valid_shell_syntax() -> None:
    """Static check: post-commit hook must parse cleanly under POSIX sh."""

    proc = subprocess.run(
        ["sh", "-n", str(POST_COMMIT_HOOK)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"post-commit hook failed sh -n syntax check:\n{proc.stderr}"


# ---------------------------------------------------------------------------
# integrity-watcher.sh smoke tests (AHMCP-19 / item I from tech-debt assessment)
# ---------------------------------------------------------------------------


def test_integrity_watcher_script_has_valid_shell_syntax() -> None:
    """Static check: integrity-watcher.sh must parse cleanly under bash -n.

    Catches the same class of regression that bit AHMCP-17: a syntax bug in
    a wrapper script that the package test suite (which only exercises
    Python imports) cannot see."""
    proc = subprocess.run(
        ["bash", "-n", str(INTEGRITY_WATCHER_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"integrity-watcher.sh failed bash -n syntax check:\n{proc.stderr}"


def test_integrity_watcher_smoke_mode_emits_valid_jsonl(tmp_path: Path) -> None:
    """End-to-end check: --smoke mode emits a valid JSONL stream with the
    expected event sequence and field set.

    The watcher's main loop runs fswatch / inotifywait which we cannot
    require in CI. The smoke mode bypasses the watcher loop entirely and
    emits one daemon_start, one synthetic write event, and one daemon_stop
    event so the JSON encoder, log rotation, and event schema can be
    tested without external dependencies."""
    # Build a tiny git repo so the watcher can resolve a primary worktree.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")

    # Make a directory the watcher's default-paths logic will pick up.
    src_dir = repo / "packages" / "agent-handoff-mcp" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "placeholder.py").write_text("# placeholder\n")

    log_path = tmp_path / "integrity-watcher.jsonl"
    env = os.environ.copy()
    env["INTEGRITY_WATCHER_LOG"] = str(log_path)

    proc = subprocess.run(
        [str(INTEGRITY_WATCHER_SCRIPT), "--smoke"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"integrity-watcher --smoke failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert log_path.exists(), f"expected log at {log_path}"

    lines = [line for line in log_path.read_text().splitlines() if line]
    assert len(lines) == 3, f"expected 3 events, got {len(lines)}: {lines}"

    events = [json.loads(line) for line in lines]
    assert events[0]["event_kind"] == "daemon_start"
    assert events[1]["event_kind"] == "write"
    assert events[2]["event_kind"] == "daemon_stop"

    # All events share the same session_id and have ISO-8601 timestamps.
    session_ids = {event["session_id"] for event in events}
    assert len(session_ids) == 1, f"expected single session_id, got {session_ids}"
    for event in events:
        assert event["ts"].endswith("Z"), f"timestamp must be UTC ISO-8601: {event['ts']}"

    # The synthetic write event must include the attribution fields the
    # forensic replay needs: git_head, git_branch, dirty list, holders list.
    write_event = events[1]
    assert "git_head" in write_event
    assert "git_branch" in write_event
    assert "dirty" in write_event
    assert "holders" in write_event
    assert isinstance(write_event["dirty"], list)
    assert isinstance(write_event["holders"], list)
    assert "path" in write_event
    assert write_event["path"].startswith(str(repo))


def test_integrity_watcher_smoke_mode_resolves_primary_worktree_from_linked(
    tmp_path: Path,
) -> None:
    """The integrity watcher must resolve the primary worktree even when
    invoked from a linked worktree (mirrors the AHMCP-16 for_repo
    resolution semantics)."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    _git(primary, "config", "user.email", "test@example.com")
    _git(primary, "config", "user.name", "Test")
    (primary / "README.md").write_text("hello\n")
    _git(primary, "add", "README.md")
    _git(primary, "commit", "-q", "-m", "init")
    src_dir = primary / "packages" / "agent-handoff-mcp" / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "placeholder.py").write_text("# placeholder\n")
    _git(primary, "add", "packages")
    _git(primary, "commit", "-q", "-m", "add packages")

    linked = tmp_path / "primary-linked"
    _git(primary, "branch", "feature/test")
    _git(primary, "worktree", "add", "-q", str(linked), "feature/test")

    log_path = tmp_path / "integrity-watcher.jsonl"
    env = os.environ.copy()
    env["INTEGRITY_WATCHER_LOG"] = str(log_path)

    # Invoke from the linked worktree. The script should still resolve
    # the primary worktree's source dir as the default watch path and
    # write to the explicit log path.
    proc = subprocess.run(
        [str(INTEGRITY_WATCHER_SCRIPT), "--smoke"],
        cwd=linked,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"smoke from linked worktree failed: {proc.stderr!r}"
    assert log_path.exists()
    events = [json.loads(line) for line in log_path.read_text().splitlines() if line]
    write_event = next(e for e in events if e["event_kind"] == "write")
    # The synthetic write must reference a path under the PRIMARY worktree,
    # not the linked one — proving the for_repo-style resolution worked.
    assert write_event["path"].startswith(str(primary.resolve())), (
        f"smoke write path {write_event['path']!r} should resolve to primary "
        f"worktree {str(primary.resolve())!r}, not linked worktree"
    )


# ---------------------------------------------------------------------------
# lint-expected-revision.py tests (AHMCP-21 / Layer 3 expected_revision class)
# ---------------------------------------------------------------------------


def test_lint_expected_revision_passes_on_current_scripts_tree() -> None:
    """AHMCP-21 / Layer 3: the lint guard at
    scripts/hooks/lint-expected-revision.py must pass on the current
    scripts/_*.py tree. If someone adds a set_handoff_state or
    update_task_status call without expected_revision, this test fails
    the package suite."""
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-expected-revision.py"
    assert lint_script.exists(), f"missing lint guard at {lint_script}"
    proc = subprocess.run(
        [sys.executable, str(lint_script)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"lint-expected-revision failed on current scripts/ tree:\n{proc.stderr}"


def test_lint_expected_revision_catches_missing_kwarg(tmp_path: Path) -> None:
    """AHMCP-21 / Layer 3 negative test: feed the guard a synthetic
    Python file that calls set_handoff_state without expected_revision
    and assert it returns exit code 1."""
    fixture = tmp_path / "_bad_inline.py"
    fixture.write_text(
        "from agent_handoff_mcp import set_handoff_state\n"
        "set_handoff_state(task_ref='T1', objective='test', status='in_progress')\n"
    )
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-expected-revision.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(tmp_path / "_*.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        f"lint guard should fail when expected_revision is missing; got exit={proc.returncode} stderr={proc.stderr!r}"
    )
    assert "set_handoff_state" in proc.stderr
    assert "expected_revision" in proc.stderr


def test_lint_expected_revision_allows_call_with_kwarg(tmp_path: Path) -> None:
    """AHMCP-21 / Layer 3 positive escape: a call that includes
    expected_revision should not be flagged."""
    fixture = tmp_path / "_good_inline.py"
    fixture.write_text(
        "from agent_handoff_mcp import set_handoff_state\n"
        "set_handoff_state(task_ref='T1', objective='test', status='in_progress', expected_revision=0)\n"
    )
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-expected-revision.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(tmp_path / "_*.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"lint guard should pass when expected_revision is present; got exit={proc.returncode} stderr={proc.stderr!r}"
    )


def test_lint_expected_revision_catches_aliased_import(tmp_path: Path) -> None:
    """AHMCP-21-BR-01 regression: the lint guard must catch calls made
    through an aliased import like
    ``from agent_handoff_mcp import set_handoff_state as write_state``
    where ``write_state(...)`` is called without ``expected_revision``."""
    fixture = tmp_path / "_alias_bad.py"
    fixture.write_text(
        "from agent_handoff_mcp import set_handoff_state as write_state\n"
        "write_state(task_ref='T1', objective='test', status='in_progress')\n"
    )
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-expected-revision.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(tmp_path / "_*.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        f"lint guard should catch aliased import; got exit={proc.returncode} stderr={proc.stderr!r}"
    )
    assert "write_state" in proc.stderr
    assert "alias for set_handoff_state" in proc.stderr


def test_lint_expected_revision_reports_syntax_errors(tmp_path: Path) -> None:
    """AHMCP-21-BR-02 regression: the lint guard must report SyntaxError
    as a violation instead of silently skipping the broken file."""
    fixture = tmp_path / "_syntax_bad.py"
    fixture.write_text(
        "from agent_handoff_mcp import set_handoff_state\nset_handoff_state(\n"  # unterminated call
    )
    lint_script = REPO_ROOT / "scripts" / "hooks" / "lint-expected-revision.py"
    proc = subprocess.run(
        [sys.executable, str(lint_script), "--paths", str(tmp_path / "_*.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1, (
        f"lint guard should fail on SyntaxError; got exit={proc.returncode} stderr={proc.stderr!r}"
    )
    assert "SyntaxError" in proc.stderr
    assert "_syntax_bad.py" in proc.stderr
