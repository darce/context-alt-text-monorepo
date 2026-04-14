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
INTEGRITY_WATCHER_SCRIPT = REPO_ROOT / "scripts" / "integrity-watcher.sh"


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
    os.chmod(repo / "scripts" / "task-start.sh", 0o755)
    os.chmod(repo / "scripts" / "task-finish.sh", 0o755)
    os.chmod(repo / "scripts" / "_task_start_inline.py", 0o755)
    os.chmod(repo / "scripts" / "_task_finish_inline.py", 0o755)
    os.chmod(repo / "scripts" / "check-task-context.py", 0o755)

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


def _read_active_row(repo: Path) -> dict[str, object] | None:
    db_path = repo / ".task-state" / "handoff.db"
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM handoff_state WHERE id = 1").fetchone()
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
    """task-start should preserve the outgoing task's real dashboard status."""
    from agent_handoff_mcp import RuntimeConfig, configure_runtime, generate_dashboard_md

    repo = _build_fake_monorepo(tmp_path)
    env = _make_env(repo)

    first = _run_script("task-start.sh", repo, "TS-DASH-1", "First task", env=env)
    assert first.returncode == 0, f"stdout={first.stdout!r} stderr={first.stderr!r}"

    second = _run_script("task-start.sh", repo, "TS-DASH-2", "Second task", env=env)
    assert second.returncode == 0, f"stdout={second.stdout!r} stderr={second.stderr!r}"

    archived = _read_archive_row(repo, "TS-DASH-1")
    assert archived is not None
    snapshot = json.loads(archived["snapshot_json"])
    assert snapshot["active"]["task_ref"] == "TS-DASH-1"
    assert snapshot["active"]["status"] == "in_progress"
    assert snapshot["active"]["target_worktree_path"].endswith("context-alt-text-monorepo-ts-dash-1")

    runtime = RuntimeConfig.for_repo(repo)
    configure_runtime(runtime)
    dashboard = generate_dashboard_md(write_file=False)
    assert dashboard["ok"] is True
    assert "TS-DASH-1" in dashboard["markdown"]
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
