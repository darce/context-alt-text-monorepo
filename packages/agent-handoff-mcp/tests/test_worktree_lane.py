from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_handoff_mcp import api


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


def test_close_dry_run_prints_cleanup_commands(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    api.configure_runtime(api.RuntimeConfig.for_workspace(repo))
    json.loads(api.set_handoff_state(task_ref="task-1", objective="lane close"))
    json.loads(
        api.upsert_worktree_lane(
            task_ref="task-1",
            lane_id="frontend",
            worktree_path=str(repo / "frontend"),
            branch="codex/frontend",
            status="closed",
        )
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "close",
            "--orchestrator-root",
            str(repo),
            "--task-ref",
            "task-1",
            "--lane-id",
            "frontend",
            "--worktree-path",
            str(repo / "frontend"),
            "--branch",
            "codex/frontend",
            "--dry-run",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "worktree remove" in result.stdout
    assert "branch -d" in result.stdout
    assert "lane-upsert" in result.stdout
    assert "closed" in result.stdout
