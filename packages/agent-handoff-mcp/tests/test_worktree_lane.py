from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "worktree-lane"


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def test_create_rejects_existing_worktree_on_wrong_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.email", "codex@example.com"], cwd=repo)
    _run(["git", "config", "user.name", "Codex"], cwd=repo)
    (repo / "README.md").write_text("hello\n")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)

    wrong_lane_path = tmp_path / "repo-frontend"
    _run(["git", "-C", str(repo), "worktree", "add", str(wrong_lane_path), "-b", "wrong-branch"], cwd=repo)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "create",
            "--orchestrator-root",
            str(repo),
            "--lane-id",
            "frontend",
            "--branch",
            "codex/expected-frontend",
            "--worktree-path",
            str(wrong_lane_path),
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "existing worktree" in result.stderr
    assert "wrong-branch" in result.stderr
    assert "codex/expected-frontend" in result.stderr
