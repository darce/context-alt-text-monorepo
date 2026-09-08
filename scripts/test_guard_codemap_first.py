from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import guard_codemap_first as guard

GUARD = Path(__file__).resolve().parent / "guard_codemap_first.py"
CODEMAP_INSTALLED = shutil.which("codebase-memory-mcp") is not None


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake repo whose layout mirrors the indexed/unindexed split."""
    for rel in ("apps/prototype-description-service", "packages/shared-contracts",
                "docs/workbay", "scripts/hooks", "benchmarks"):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "apps/prototype-description-service/main.py").write_text("x = 1\n")
    monkeypatch.setattr(guard.shutil, "which", lambda _name: "/usr/local/bin/codebase-memory-mcp")
    monkeypatch.delenv("CODEMAP_FIRST_DISABLE", raising=False)
    return tmp_path


def grep(**kwargs) -> dict:
    return {"tool_name": "Grep", "tool_input": kwargs}


def bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# --- Grep tool -------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        grep(pattern="ClusterRepository", path="apps"),
        grep(pattern="build_context_pack", path="packages/shared-contracts"),
        grep(pattern="def resolve_runtime"),  # repo-wide sweep
        grep(pattern=r"\bOrtYuNetDetector\b", path="apps"),
        grep(pattern="OrtSFaceEmbedder", path="apps", glob="*.py"),
        grep(pattern="OrtSFaceEmbedder", path="apps", glob="*.{py,md}"),
    ],
)
def test_blocks_symbol_search_over_indexed_roots(repo: Path, payload: dict) -> None:
    reason = guard.decide(payload, repo)
    assert reason is not None
    assert "codebase-memory-mcp cli search_graph" in reason
    assert "CODEMAP_OK=1" in reason


@pytest.mark.parametrize(
    "payload",
    [
        grep(pattern="ClusterRepository", path="docs"),          # not indexed
        grep(pattern="ClusterRepository", path="scripts/hooks"),  # not indexed
        grep(pattern="ClusterRepository", path="benchmarks"),     # not indexed
        grep(pattern="retain_all|retain_none", path="apps"),      # regex alternation
        grep(pattern="TODO: fix .* later", path="apps"),          # free text
        grep(pattern="ab", path="apps"),                          # too short to be a symbol
        grep(pattern="ClusterRepository", path="apps", glob="*.md"),
        grep(pattern="ClusterRepository", path="apps", type="yaml"),
        grep(pattern="x = 1", path="apps/prototype-description-service/main.py"),
    ],
)
def test_allows_everything_outside_the_index(repo: Path, payload: dict) -> None:
    assert guard.decide(payload, repo) is None


def test_allows_single_file_operand(repo: Path) -> None:
    payload = grep(pattern="ClusterRepository",
                   path="apps/prototype-description-service/main.py")
    assert guard.decide(payload, repo) is None


@pytest.mark.parametrize("pattern", ["foo^bar", "foo$bar", r"foo\bbar"])
def test_internal_regex_anchors_remain_raw_text_search(repo: Path, pattern: str) -> None:
    """Anchors inside a pattern are regex syntax, not codemap identifiers."""
    assert guard._pattern_is_symbolic(pattern) is None
    assert guard.decide(grep(pattern=pattern, path="apps"), repo) is None


def test_negative_glob_does_not_exclude_indexed_code(repo: Path) -> None:
    """Excluding prose still leaves an indexed code-root search in scope."""
    payload = grep(pattern="ClusterRepository", path="apps", glob="!*.md")
    assert guard.decide(payload, repo) is not None


# --- Bash ------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "rg ClusterRepository apps/",
        "rg -n 'OrtYuNetDetector' apps packages",
        "grep -rn build_context_pack apps/",
        "rg 'def resolve_runtime'",                     # rg recurses from cwd
        "rg -e ClusterRepository apps/",
        "CODEMAP_UNRELATED=1 rg ClusterRepository apps/",
        "cd apps && rg ClusterRepository .",
        "rg -g '*.md' -g '*.py' ClusterRepository apps/",
        "rg -t yaml -t py ClusterRepository apps/",
    ],
)
def test_blocks_bash_symbol_sweeps(repo: Path, command: str) -> None:
    assert guard.decide(bash(command), repo) is not None


@pytest.mark.parametrize(
    "command",
    [
        "CODEMAP_OK=1 rg ClusterRepository apps/",      # declared escape
        "env CODEMAP_OK=1 rg ClusterRepository apps/",  # declared escape via env
        "git log --oneline | grep ClusterRepository",   # filtering command output
        "cat foo.txt | grep -n ClusterRepository",
        "git log -p | rg ClusterRepository",            # rg on stdin, not the tree
        "git diff | rg 'def resolve_runtime'",
        "ls apps/ | rg ClusterRepository apps/",        # path operand, still stdin-fed
        "grep ClusterRepository",                       # plain grep reads stdin
        "rg ClusterRepository docs/",
        "rg -t md ClusterRepository apps/",
        "rg -g '*.md' ClusterRepository apps/",
        "rg --files-with-matches ClusterRepository apps/",
        "rg 'retain_all|retain_none' apps/",
        "ls apps/ && echo done",
        "rg ClusterRepository /some/other/repo",
    ],
)
def test_allows_non_symbol_bash(repo: Path, command: str) -> None:
    assert guard.decide(bash(command), repo) is None


def test_escape_marker_must_be_an_assignment(repo: Path) -> None:
    """Mentioning CODEMAP_OK in output must not bypass the guard."""
    command = "echo CODEMAP_OK=1 && rg ClusterRepository apps/"
    assert guard.decide(bash(command), repo) is not None


def test_cd_into_indexed_root_is_guarded(repo: Path) -> None:
    command = "cd apps && rg ClusterRepository ."
    assert guard.decide(bash(command), repo) is not None


def test_cd_outside_repo_does_not_infer_an_indexed_path(repo: Path) -> None:
    command = "cd /definitely/not/this/repo && rg ClusterRepository apps/"
    assert guard.decide(bash(command), repo) is None


def test_failed_cd_fails_open(repo: Path) -> None:
    command = "cd apps/missing && rg ClusterRepository ."
    assert guard.decide(bash(command), repo) is None


def test_claude_codemap_hook_has_timeout() -> None:
    settings_path = GUARD.parent.parent / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    codemap = next(
        entry for entry in settings["hooks"]["PreToolUse"]
        if entry.get("matcher") == "Grep|Bash"
    )
    assert codemap["hooks"][0]["timeout"] == 5


# --- Fail-open guarantees --------------------------------------------------

def test_kill_switch(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEMAP_FIRST_DISABLE", "1")
    assert guard.decide(grep(pattern="ClusterRepository", path="apps"), repo) is None


def test_allows_when_codemap_cli_absent(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard.shutil, "which", lambda _name: None)
    assert guard.decide(grep(pattern="ClusterRepository", path="apps"), repo) is None


def test_project_name_resolves_to_the_canonical_root(tmp_path: Path) -> None:
    """A linked worktree is not indexed; the advice must name the root project."""
    main = tmp_path / "proj"
    main.mkdir()
    run = lambda *a: subprocess.run(a, cwd=main, capture_output=True, check=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    (main / "f.txt").write_text("x\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "init")
    linked = tmp_path / "proj-wt"
    run("git", "worktree", "add", "-q", "-b", "feature/x", str(linked))

    assert guard._project_name(linked) == guard._project_name(main)
    assert "proj-wt" not in guard._project_name(linked)


def test_ignores_other_tools(repo: Path) -> None:
    assert guard.decide({"tool_name": "Read", "tool_input": {"file_path": "x"}}, repo) is None


def _run(stdin: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=stdin,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_zero_on_garbage_stdin(tmp_path: Path) -> None:
    for payload in ("", "   ", "not json", '{"tool_input": "a string"}'):
        assert _run(payload, tmp_path).returncode == 0


@pytest.mark.skipif(not CODEMAP_INSTALLED, reason="codebase-memory-mcp not installed")
def test_cli_blocks_with_exit_2(repo: Path) -> None:
    payload = json.dumps({**grep(pattern="ClusterRepository", path="apps"), "cwd": str(repo)})
    result = _run(payload, repo)
    assert result.returncode == 2
    assert "codebase-memory-mcp cli search_graph" in result.stderr
