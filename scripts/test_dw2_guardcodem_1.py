from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from scripts import guard_codemap_first as guard


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel in ("apps", "packages", "docs"):
        (tmp_path / rel).mkdir()
    monkeypatch.setattr(guard.shutil, "which", lambda _name: "/usr/local/bin/codebase-memory-mcp")
    monkeypatch.delenv("CODEMAP_FIRST_DISABLE", raising=False)
    return tmp_path


def grep(**kwargs) -> dict:
    return {"tool_name": "Grep", "tool_input": kwargs}


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.mark.parametrize(
    "payload",
    [
        grep(pattern="ClusterRepository", path="."),
        bash("rg ClusterRepository ."),
    ],
)
def test_relative_search_uses_payload_cwd(repo: Path, payload: dict) -> None:
    payload["cwd"] = str(repo / "docs")
    assert guard.decide(payload, repo) is None


def test_shell_comment_does_not_create_search_command(repo: Path) -> None:
    assert guard.decide(bash("echo ok # ; rg ClusterRepository apps"), repo) is None


def test_brace_glob_excludes_prose_suffixes(repo: Path) -> None:
    command = "rg -g '*.{md,txt}' ClusterRepository apps"
    assert guard.decide(bash(command), repo) is None


def test_replace_value_is_not_the_search_pattern(repo: Path) -> None:
    command = "rg --replace replacement 'a|b' apps"
    assert guard.decide(bash(command), repo) is None


def test_main_shares_bounded_git_metadata_lookup(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict]] = []

    def fake_run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        if "--show-toplevel" in args and "--git-common-dir" in args:
            stdout = f"{repo}\n{repo / '.git'}\n"
        elif "--show-toplevel" in args:
            stdout = f"{repo}\n"
        elif "--git-common-dir" in args:
            stdout = f"{repo / '.git'}\n"
        else:
            raise AssertionError(f"unexpected subprocess: {args}")
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(guard.subprocess, "run", fake_run)
    monkeypatch.setattr(
        guard.sys,
        "stdin",
        io.StringIO(
            json.dumps({**bash("rg ClusterRepository apps"), "cwd": str(repo)})
        ),
    )

    assert guard.main() == 2
    assert len(calls) == 1
    assert calls[0][1]["timeout"] <= 1
