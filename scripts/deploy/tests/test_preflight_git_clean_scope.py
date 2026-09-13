"""preflight_git_clean blocks only on changes to paths that reach the deploy."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"

TRACKED = {
    "apps/prototype-description-service/scene/app.py": "print('v1')\n",
    "scripts/deploy/lib/helper.sh": "true\n",
    ".claude/settings.json": "{}\n",
    "docs/notes.md": "notes\n",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, body in TRACKED.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
    return root


def _run(repo: Path, env_name: str, allow_dirty: str = "0") -> subprocess.CompletedProcess[str]:
    driver = f'''
source "{SCRIPT}"
GREEN=; YELLOW=; RED=; RESET=
REPO_ROOT="{repo}"
ACX_ALLOW_DIRTY={allow_dirty}
preflight_git_clean {env_name}
echo PREFLIGHT_OK
'''
    return subprocess.run(
        ["bash", "-c", driver], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    )


@pytest.mark.parametrize("env_name", ["dev", "staging", "prod"])
def test_clean_tree_passes(repo: Path, env_name: str) -> None:
    result = _run(repo, env_name)
    assert "PREFLIGHT_OK" in result.stdout, result.stderr


@pytest.mark.parametrize("env_name", ["dev", "staging", "prod"])
@pytest.mark.parametrize("rel", [".claude/settings.json", "docs/notes.md"])
def test_changes_outside_deploy_inputs_do_not_block(repo: Path, env_name: str, rel: str) -> None:
    (repo / rel).write_text("changed\n")
    (repo / ".codex").mkdir()
    (repo / ".codex" / "untracked.toml").write_text("x = 1\n")
    result = _run(repo, env_name)
    assert "PREFLIGHT_OK" in result.stdout, result.stderr


@pytest.mark.parametrize("rel", ["apps/prototype-description-service/scene/app.py", "scripts/deploy/lib/helper.sh"])
def test_modified_deploy_input_blocks_dev_without_override(repo: Path, rel: str) -> None:
    (repo / rel).write_text("changed\n")
    result = _run(repo, "dev")
    assert "PREFLIGHT_OK" not in result.stdout
    assert "dirty deploy inputs (dev)" in result.stdout + result.stderr
    assert rel in result.stderr


def test_untracked_service_file_blocks_because_rsync_ships_it(repo: Path) -> None:
    (repo / "apps/prototype-description-service/scene/new_module.py").write_text("x = 1\n")
    result = _run(repo, "staging")
    assert "PREFLIGHT_OK" not in result.stdout
    assert "Deploy inputs must be clean for staging deploys." in result.stdout + result.stderr


def test_override_applies_to_dev_only(repo: Path) -> None:
    (repo / "apps/prototype-description-service/scene/app.py").write_text("changed\n")
    assert "PREFLIGHT_OK" in _run(repo, "dev", allow_dirty="1").stdout
    assert "PREFLIGHT_OK" not in _run(repo, "prod", allow_dirty="1").stdout


def test_git_failure_fails_closed(tmp_path: Path) -> None:
    result = _run(tmp_path / "not-a-repo", "dev")
    assert "PREFLIGHT_OK" not in result.stdout
    assert "git status failed for deploy inputs" in result.stdout + result.stderr
