"""Tests for working_tree integrity helpers and MCP tools."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    post_merge_integrity_check,
    working_tree_integrity_check,
)
from agent_handoff_mcp.working_tree import _check_working_tree_integrity


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    _git("config", "commit.gpgsign", "false", cwd=path)


def _commit_file(path: Path, name: str, content: str, msg: str = "c") -> str:
    (path / name).write_text(content)
    _git("add", name, cwd=path)
    _git("commit", "-q", "-m", msg, cwd=path)
    return _git("rev-parse", "HEAD", cwd=path)


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", "1")
    monkeypatch.setenv("AGENT_HANDOFF_SKIP_SHA_VALIDATION", "1")
    _init_repo(tmp_path)
    _commit_file(tmp_path, "a.txt", "one\n", "initial")
    configure_runtime(RuntimeConfig.for_workspace(tmp_path))
    return tmp_path


def test_integrity_check_clean_tree(repo: Path) -> None:
    result = _check_working_tree_integrity()
    assert result["ok"] is True
    assert result["dirty_paths"] == []
    assert result["unexpected_dirty"] == []


def test_integrity_check_detects_unexpected_dirty(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    result = _check_working_tree_integrity()
    assert result["ok"] is False
    assert result["dirty_paths"] == ["a.txt"]
    assert result["unexpected_dirty"] == ["a.txt"]


def test_integrity_check_allowlist_via_param(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    result = _check_working_tree_integrity(expected_dirty=["a.txt"])
    assert result["ok"] is True
    assert result["unexpected_dirty"] == []
    assert result["allowlist_source"] == "param:expected_dirty"


def test_integrity_check_allowlist_via_file(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    state_dir = repo / ".task-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "dirty-allowlist").write_text("# expected\na.txt\n")
    configure_runtime(RuntimeConfig.for_workspace(repo))
    result = _check_working_tree_integrity()
    assert result["ok"] is True


def test_working_tree_integrity_check_tool_envelope(repo: Path) -> None:
    (repo / "a.txt").write_text("two\n")
    envelope = working_tree_integrity_check()
    assert envelope["ok"] is False
    assert envelope["data"]["unexpected_dirty"] == ["a.txt"]


def test_post_merge_integrity_check_clean(repo: Path) -> None:
    sha = _git("rev-parse", "HEAD", cwd=repo)
    envelope = post_merge_integrity_check(merged_sha=sha, expected_changed_files=[])
    assert envelope["ok"] is True
    assert envelope["data"]["divergence"] == []


def test_post_merge_integrity_check_detects_divergence(repo: Path) -> None:
    sha = _git("rev-parse", "HEAD", cwd=repo)
    (repo / "a.txt").write_text("drift\n")
    envelope = post_merge_integrity_check(merged_sha=sha, expected_changed_files=[])
    assert envelope["ok"] is False
    assert envelope["data"]["divergence"] == ["a.txt"]


def test_post_merge_integrity_check_accepts_expected_change(repo: Path) -> None:
    sha = _git("rev-parse", "HEAD", cwd=repo)
    (repo / "a.txt").write_text("expected edit\n")
    envelope = post_merge_integrity_check(merged_sha=sha, expected_changed_files=["a.txt"])
    assert envelope["ok"] is True
    assert envelope["data"]["divergence"] == []


def test_post_merge_integrity_check_rejects_empty_sha(repo: Path) -> None:
    envelope = post_merge_integrity_check(merged_sha="", expected_changed_files=[])
    assert envelope["ok"] is False
    assert "merged_sha" in envelope["data"]["error"]
