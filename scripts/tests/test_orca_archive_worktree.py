from __future__ import annotations

import errno
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = REPO_ROOT / "scripts/orca/archive_worktree.py"
TASK_BRANCH = "feature/orca-9"


@dataclass(frozen=True)
class Repos:
    root: Path
    primary: Path
    worktree: Path
    env: dict[str, str]


def _hermetic_env(tmp_path: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("GIT_", "ORCA_"))}
    home = tmp_path / "home"
    home.mkdir()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CEILING_DIRECTORIES=str(tmp_path),
    )
    return env


def _git(env: dict[str, str], *args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, env=env).stdout


def _status(repos: Repos, checkout: Path) -> str:
    # The test's own reads must not refresh the index, or the clean case could
    # not tell whether the hook wrote it.
    return _git({**repos.env, "GIT_OPTIONAL_LOCKS": "0"}, "-C", str(checkout), "status", "--porcelain=v1", "-uall")


def _snapshot(root: Path) -> dict[str, bytes | str]:
    entries: dict[str, bytes | str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                entries[rel] = f"symlink:{os.readlink(path)}"
            elif path.is_dir():
                entries[rel] = "dir"
            else:
                entries[rel] = path.read_bytes()
    return entries


@pytest.fixture
def repos(tmp_path: Path) -> Repos:
    env = _hermetic_env(tmp_path)
    primary = tmp_path / "primary"
    worktree = tmp_path / "worktrees" / "orca-9"
    _git(env, "-c", "init.defaultBranch=main", "init", "-q", str(primary))
    _git(env, "-C", str(primary), "config", "user.name", "Archive Hook Test")
    _git(env, "-C", str(primary), "config", "user.email", "archive-hook-test@example.invalid")
    (primary / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (primary / "README.md").write_text("tracked\n", encoding="utf-8")
    (primary / "src").mkdir()
    (primary / "src/app.py").write_text("print('app')\n", encoding="utf-8")
    _git(env, "-C", str(primary), "add", "-A")
    _git(env, "-C", str(primary), "commit", "-q", "-m", "base")
    _git(env, "-C", str(primary), "worktree", "add", "-q", "-b", TASK_BRANCH, str(worktree))
    return Repos(root=tmp_path.resolve(), primary=primary.resolve(), worktree=worktree.resolve(), env=env)


def _run_archive(
    repos: Repos,
    *,
    worktree: Path | str | None,
    root: Path | str | None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**repos.env, "ORCA_WORKSPACE_NAME": "orca-9", **(extra_env or {})}
    if worktree is not None:
        env["ORCA_WORKTREE_PATH"] = str(worktree)
    if root is not None:
        env["ORCA_ROOT_PATH"] = str(root)
    return subprocess.run(
        [sys.executable, str(ARCHIVE)],
        cwd=repos.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _run_read_only(
    repos: Repos, *, worktree: Path | str | None, root: Path | str | None
) -> subprocess.CompletedProcess[str]:
    """Run the hook and assert it changed neither file bytes nor git status anywhere."""
    status_before = (_status(repos, repos.primary), _status(repos, repos.worktree))
    files_before = _snapshot(repos.root)
    completed = _run_archive(repos, worktree=worktree, root=root)
    assert _snapshot(repos.root) == files_before, "the archive hook must never write, move, or delete files"
    assert (_status(repos, repos.primary), _status(repos, repos.worktree)) == status_before
    assert completed.stdout == "", "stdout is reserved for documented machine output; this hook has none"
    return completed


def _index_path(repos: Repos) -> Path:
    raw = _git(repos.env, "-C", str(repos.worktree), "rev-parse", "--path-format=absolute", "--git-path", "index")
    return Path(raw.strip())


def test_clean_worktree_allows_archive_without_touching_tree_or_index(repos: Repos) -> None:
    # A stale stat makes a lock-taking `git status` refresh and rewrite the index.
    readme = repos.worktree / "README.md"
    os.utime(readme, (readme.stat().st_atime - 86_400, readme.stat().st_mtime - 86_400))
    index = _index_path(repos)
    index_before = index.read_bytes()

    completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)

    assert completed.returncode == 0, completed.stderr
    assert index.read_bytes() == index_before
    assert "clean" in completed.stderr
    assert "does not close the WorkBay task row" in completed.stderr
    assert "make task-finish TASK=ORCA-9" in completed.stderr
    assert str(repos.primary) in completed.stderr


def _modify_tracked(repos: Repos) -> str:
    (repos.worktree / "README.md").write_text("edited in the worktree\n", encoding="utf-8")
    return "README.md"


def _stage_new_file(repos: Repos) -> str:
    (repos.worktree / "src/added.py").write_text("print('staged')\n", encoding="utf-8")
    _git(repos.env, "-C", str(repos.worktree), "add", "src/added.py")
    return "src/added.py"


def _add_untracked(repos: Repos) -> str:
    # Nested so only --untracked-files=all names the file instead of "notes/".
    (repos.worktree / "notes").mkdir()
    (repos.worktree / "notes/todo.txt").write_text("unsaved idea\n", encoding="utf-8")
    return "notes/todo.txt"


@pytest.mark.parametrize("make_dirty", [_modify_tracked, _stage_new_file, _add_untracked])
def test_dirty_worktree_refuses_archive_and_lists_the_path(repos: Repos, make_dirty) -> None:
    dirty_path = make_dirty(repos)

    completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)

    assert completed.returncode == 1, completed.stderr
    listed = [line.strip() for line in completed.stderr.splitlines()]
    assert any(line.endswith(f" {dirty_path}") for line in listed), completed.stderr
    assert "rg-017" in completed.stderr
    assert "Commit task-owned changes on the branch" in completed.stderr
    assert "make task-finish TASK=ORCA-9" in completed.stderr
    assert str(repos.primary) in completed.stderr
    assert (repos.worktree / dirty_path).exists()


@pytest.mark.parametrize(("count", "more_line"), [(50, None), (51, "... and 1 more"), (57, "... and 7 more")])
def test_dirty_listing_caps_at_fifty_paths(repos: Repos, count: int, more_line: str | None) -> None:
    bulk = repos.worktree / "bulk"
    bulk.mkdir()
    for i in range(count):
        (bulk / f"f{i:03d}.txt").write_text(f"{i}\n", encoding="utf-8")

    completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)

    assert completed.returncode == 1, completed.stderr
    listed = [line for line in completed.stderr.splitlines() if "bulk/f" in line]
    assert len(listed) == min(count, 50)
    assert f"{count} dirty path" in completed.stderr
    lines = completed.stderr.splitlines()
    overflow = [i for i, line in enumerate(lines) if line.strip().startswith("... and ")]
    if more_line is None:
        assert overflow == []
    else:
        assert [lines[i].strip() for i in overflow] == [more_line]
        assert overflow[0] == lines.index(listed[-1]) + 1, "the overflow line must follow the 50th path"


def test_gitignored_files_alone_stay_clean(repos: Repos) -> None:
    (repos.worktree / "debug.log").write_text("noise\n", encoding="utf-8")
    (repos.worktree / "build").mkdir()
    (repos.worktree / "build/out.bin").write_bytes(b"\x00artifact")

    completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)

    assert completed.returncode == 0, completed.stderr
    assert "debug.log" not in completed.stderr
    assert "build/out.bin" not in completed.stderr


def test_inherited_git_dir_cannot_mask_a_dirty_worktree(repos: Repos) -> None:
    _add_untracked(repos)
    leaked = {"GIT_DIR": str(repos.primary / ".git"), "GIT_WORK_TREE": str(repos.primary)}

    completed = _run_archive(repos, worktree=repos.worktree, root=repos.primary, extra_env=leaked)

    assert completed.returncode == 1, completed.stderr
    assert "notes/todo.txt" in completed.stderr


def test_detached_head_falls_back_to_a_task_ref_placeholder(repos: Repos) -> None:
    _git(repos.env, "-C", str(repos.worktree), "checkout", "-q", "--detach")

    completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)

    assert completed.returncode == 0, completed.stderr
    assert "make task-finish TASK=<TASK-REF>" in completed.stderr


def test_subdirectory_of_a_linked_worktree_checks_the_whole_worktree(repos: Repos) -> None:
    _modify_tracked(repos)

    completed = _run_read_only(repos, worktree=repos.worktree / "src", root=repos.primary)

    assert completed.returncode == 1, completed.stderr
    assert "README.md" in completed.stderr


def _refusal_case(name: str, repos: Repos) -> tuple[Path | None, Path | None, str]:
    plain = repos.root / "plain"
    plain.mkdir()
    a_file = repos.root / "plain/file.txt"
    a_file.write_text("not a directory\n", encoding="utf-8")
    link = repos.root / "primary-link"
    link.symlink_to(repos.primary, target_is_directory=True)
    cases: dict[str, tuple[Path | None, Path | None, str]] = {
        "missing": (None, repos.primary, "ORCA_WORKTREE_PATH is not set"),
        "absent": (repos.root / "gone", repos.primary, "is not a directory"),
        "file": (a_file, repos.primary, "is not a directory"),
        "not-git": (plain, repos.primary, "is not inside a git worktree"),
        "primary": (repos.primary, repos.primary, "primary checkout"),
        "primary-symlink": (link, repos.primary, "primary checkout"),
        "primary-subdir": (repos.primary / "src", repos.primary, "primary checkout"),
    }
    return cases[name]


@pytest.mark.parametrize(
    "case", ["missing", "absent", "file", "not-git", "primary", "primary-symlink", "primary-subdir"]
)
def test_preconditions_refuse_with_exit_two(repos: Repos, case: str) -> None:
    worktree, root, reason = _refusal_case(case, repos)

    completed = _run_read_only(repos, worktree=worktree, root=root)

    assert completed.returncode == 2, completed.stderr
    assert completed.stderr.startswith("archive_worktree: "), completed.stderr
    assert "ORCA_WORKTREE_PATH" in completed.stderr
    assert reason in completed.stderr


def test_empty_worktree_env_counts_as_missing(repos: Repos) -> None:
    completed = _run_read_only(repos, worktree="", root=repos.primary)

    assert completed.returncode == 2, completed.stderr
    assert "ORCA_WORKTREE_PATH is not set" in completed.stderr


def _assert_never_authorizes(stderr: str) -> None:
    assert "is clean" not in stderr, stderr
    assert "may archive" not in stderr, stderr


def test_unreadable_untracked_directory_refuses_archive(repos: Repos) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory mode bits, so git can still read the directory")
    private = repos.worktree / "private"
    private.mkdir()
    (private / "unsaved.txt").write_text("work that exists nowhere else\n", encoding="utf-8")
    private.chmod(0)
    try:
        completed = _run_read_only(repos, worktree=repos.worktree, root=repos.primary)
    finally:
        private.chmod(0o700)

    assert completed.returncode == 2, completed.stderr
    assert "could not open directory 'private/'" in completed.stderr
    assert "could not fully scan" in completed.stderr
    assert str(repos.worktree) in completed.stderr
    assert "chmod u+rx" in completed.stderr
    assert "retry" in completed.stderr
    _assert_never_authorizes(completed.stderr)
    assert (private / "unsaved.txt").exists()


def _stub_git(repos: Repos) -> Path:
    """Put a git first on PATH whose `status` is scripted and everything else is real git."""
    real_git = shutil.which("git", path=repos.env.get("PATH"))
    assert real_git is not None
    bin_dir = repos.root / "stub-bin"
    bin_dir.mkdir()
    stub = bin_dir / "git"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$3" = status ]; then\n'
        "  printf '%s' \"$STUB_STATUS_STDOUT\"\n"
        "  printf '%s' \"$STUB_STATUS_STDERR\" >&2\n"
        '  exit "$STUB_STATUS_EXIT"\n'
        "fi\n"
        f'exec {shlex.quote(real_git)} "$@"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir


@pytest.mark.parametrize(
    ("stdout", "stderr", "exit_code", "expected"),
    [
        ("", "warning: something\n", 0, 2),
        ("?? notes/todo.txt\n", "warning: something\n", 0, 2),
        ("", "fatal: index file corrupt\n", 128, 2),
        ("?? notes/todo.txt\n", "", 0, 1),
        ("", "", 0, 0),
    ],
    ids=["warning-exit-0", "warning-with-dirty-stdout", "nonzero-exit", "stdout-only-dirty", "clean"],
)
def test_git_status_stderr_means_the_scan_is_incomplete(
    repos: Repos, stdout: str, stderr: str, exit_code: int, expected: int
) -> None:
    bin_dir = _stub_git(repos)
    extra = {
        "PATH": f"{bin_dir}{os.pathsep}{repos.env.get('PATH', '')}",
        "STUB_STATUS_STDOUT": stdout,
        "STUB_STATUS_STDERR": stderr,
        "STUB_STATUS_EXIT": str(exit_code),
    }

    completed = _run_archive(repos, worktree=repos.worktree, root=repos.primary, extra_env=extra)

    assert completed.returncode == expected, completed.stderr
    assert completed.stdout == ""
    if stderr:
        assert stderr in completed.stderr, "git's own message must reach the operator verbatim"
    # A warning is not a dirty path (finding 14108): the channels never mix.
    assert "  warning: something" not in completed.stderr.splitlines()
    if expected == 2:
        assert "could not fully scan" in completed.stderr
        assert "dirty path" not in completed.stderr
        _assert_never_authorizes(completed.stderr)
    elif expected == 1:
        assert "  ?? notes/todo.txt" in completed.stderr.splitlines()
        assert "1 dirty path(s)" in completed.stderr
    else:
        assert f"{repos.worktree} is clean; Orca may archive it." in completed.stderr


def _load_archive_module():
    spec = importlib.util.spec_from_file_location("orca_archive_worktree_under_test", ARCHIVE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failing_step", ["status", "symbolic-ref"])
def test_git_launch_failure_after_rev_parse_refuses_without_traceback(
    repos: Repos, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failing_step: str
) -> None:
    archive = _load_archive_module()
    for key in [key for key in os.environ if key not in repos.env]:
        monkeypatch.delenv(key)
    for key, value in repos.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("ORCA_WORKTREE_PATH", str(repos.worktree))
    monkeypatch.setenv("ORCA_ROOT_PATH", str(repos.primary))
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[3:4] == [failing_step]:
            raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), "git")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(archive.subprocess, "run", run)

    returncode = archive.main([])

    captured = capsys.readouterr()
    assert returncode == 2, captured.err
    assert captured.out == ""
    assert captured.err.startswith("archive_worktree: cannot run git ("), captured.err
    assert "put git on PATH" in captured.err
    assert "Traceback" not in captured.err
    _assert_never_authorizes(captured.err)
