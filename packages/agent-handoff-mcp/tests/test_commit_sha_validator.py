"""Regression tests for the git-backed commit-SHA validator.

These tests exercise ``_validate_and_expand_commit_sha`` with validation
*enabled* (i.e. ``AGENT_HANDOFF_SKIP_SHA_VALIDATION`` is not set).  They
spin up a real temporary git repository so that the ``git rev-parse``
subprocess call in the validator has a live repo to work against.

The ``conftest.py`` for this package globally sets
``AGENT_HANDOFF_SKIP_SHA_VALIDATION=1`` before any import, which prevents
the validator from calling out to git in the rest of the test suite.  Each
test in this module temporarily removes that env var for the duration of
the call under test.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_handoff_mcp.runtime import RuntimeConfig
from agent_handoff_mcp.shared_write_context import (
    InvalidCommitShaError,
    _validate_and_expand_commit_sha,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    """Create a minimal git repo and return (repo_path, full_HEAD_sha)."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tmp_path, head_sha


@pytest.fixture(autouse=True)
def _enable_validation(git_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable SHA validation for every test in this module.

    The global conftest sets AGENT_HANDOFF_SKIP_SHA_VALIDATION=1 before
    imports.  We remove it here so the validator actually calls git.  We
    also point the runtime workspace_root at the temporary git repo so
    ``_git_repo_root()`` resolves to it.
    """
    repo_path, _ = git_repo
    monkeypatch.delenv("AGENT_HANDOFF_SKIP_SHA_VALIDATION", raising=False)
    runtime = RuntimeConfig.for_workspace(
        repo_path,
        state_dir=repo_path / ".task-state",
        current_task_path=repo_path / "CURRENT_TASK.json",
    )
    from agent_handoff_mcp import shared_write_context

    monkeypatch.setattr(shared_write_context, "get_runtime_config", lambda: runtime)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_sha_accepted_and_returned_unchanged(git_repo: tuple[Path, str]) -> None:
    _, head_sha = git_repo
    result = _validate_and_expand_commit_sha(head_sha)
    assert result == head_sha


def test_abbreviated_sha_expanded_to_full_40_chars(git_repo: tuple[Path, str]) -> None:
    _, head_sha = git_repo
    abbrev = head_sha[:8]
    result = _validate_and_expand_commit_sha(abbrev)
    assert result == head_sha
    assert len(result) == 40  # type: ignore[arg-type]


def test_nonexistent_sha_raises(git_repo: tuple[Path, str]) -> None:
    """A hex string that does not point at a real commit is rejected."""
    with pytest.raises(InvalidCommitShaError, match="does not resolve to a real commit"):
        _validate_and_expand_commit_sha("deadbeef1234")


def test_non_hex_string_raises() -> None:
    """A non-hex string is rejected before git is even called."""
    with pytest.raises(InvalidCommitShaError, match="not a hex string"):
        _validate_and_expand_commit_sha("not-a-sha")


def test_none_passes_through() -> None:
    """None means 'no provenance claim'; the validator returns it as-is."""
    assert _validate_and_expand_commit_sha(None) is None


def test_empty_string_passes_through() -> None:
    """An empty string is treated the same as no value provided."""
    assert _validate_and_expand_commit_sha("") == ""


def test_short_hex_below_four_chars_raises() -> None:
    """Hex strings shorter than 4 chars are too ambiguous; they are rejected."""
    with pytest.raises(InvalidCommitShaError, match="not a hex string"):
        _validate_and_expand_commit_sha("abc")
