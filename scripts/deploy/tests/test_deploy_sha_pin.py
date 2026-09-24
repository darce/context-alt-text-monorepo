"""Regression coverage for immutable per-run deploy commit selection."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Deploy SHA test")
    _git(repo, "config", "user.email", "deploy-sha@example.invalid")
    (repo / "deploy-input.txt").write_text("A\n")
    _git(repo, "add", "deploy-input.txt")
    _git(repo, "commit", "-qm", "A")
    commit_a = _git(repo, "rev-parse", "HEAD")
    (repo / "deploy-input.txt").write_text("B\n")
    _git(repo, "commit", "-qam", "B")
    commit_b = _git(repo, "rev-parse", "HEAD")
    subprocess.run(
        ["git", "init", "-q", "--bare", "--initial-branch=main", str(origin)],
        check=True,
    )
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-qu", "origin", "main")
    return repo, commit_a, commit_b


def _run_shell(driver: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("GIT_REF", None)
    env.pop("DEPLOY_SHA", None)
    env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", driver],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=20,
    )


def _source(repo: Path) -> str:
    return f'source {shlex.quote(str(SCRIPT))}\nREPO_ROOT={shlex.quote(str(repo))}\n'


def test_pin_survives_head_move_and_verify_uses_original_sha(tmp_path: Path) -> None:
    repo, commit_a, commit_b = _repo(tmp_path)
    _git(repo, "checkout", "--quiet", "--detach", commit_a)
    driver = _source(repo) + f'''
pin_deploy_sha
git -C "$REPO_ROOT" checkout --quiet --detach {shlex.quote(commit_b)}
test "$DEPLOY_SHA" = {shlex.quote(commit_a)}
curl() {{ printf '{{"commit_sha":"%s","image_variant":"recognition"}}\\n200\\n' {shlex.quote(commit_a)}; }}
verify_running_image_matches_deployed() {{ :; }}
verify_live_gpu_snapshots() {{ :; }}
ACX_VERIFY_EXPECT_LOCAL=1
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
do_verify dev
'''
    result = _run_shell(driver)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"matches DEPLOY_SHA={commit_a}" in result.stdout
    assert "SKEW:" not in result.stderr


def test_only_pin_deploy_sha_resolves_git_ref() -> None:
    source = SCRIPT.read_text()
    matches = list(
        re.finditer(
            r'git\s+-C\s+"\$\{REPO_ROOT\}"\s+rev-parse[^\n]*"\$\{GIT_REF\}',
            source,
        )
    )
    pin = re.search(r"(?ms)^pin_deploy_sha\(\) \{\n(.*?)^\}", source)

    assert pin is not None
    assert len(matches) == 1
    assert pin.start(1) <= matches[0].start() <= pin.end(1)


def test_explicit_historical_ref_requires_checkout_at_that_sha(tmp_path: Path) -> None:
    repo, commit_a, commit_b = _repo(tmp_path)
    driver = _source(repo) + f'''
pin_deploy_sha
preflight_branch_synced prod
'''
    _git(repo, "checkout", "--quiet", "--detach", commit_b)
    result = _run_shell(driver, GIT_REF=commit_a)

    assert result.returncode != 0
    assert "checkout or detached worktree" in result.stderr
    assert commit_a[:8] in result.stderr
    assert commit_b[:8] in result.stderr


def test_explicit_historical_ancestor_passes_with_warning(tmp_path: Path) -> None:
    repo, commit_a, _ = _repo(tmp_path)
    _git(repo, "checkout", "--quiet", "--detach", commit_a)
    result = _run_shell(
        _source(repo) + "pin_deploy_sha\npreflight_branch_synced prod\n",
        GIT_REF=commit_a,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"deploying historical {commit_a[:8]}" in result.stderr
    assert "origin/main is " in result.stderr


def test_default_ref_behind_origin_main_still_fails(tmp_path: Path) -> None:
    repo, commit_a, _ = _repo(tmp_path)
    _git(repo, "checkout", "--quiet", "--detach", commit_a)
    result = _run_shell(
        _source(repo) + "pin_deploy_sha\npreflight_branch_synced prod\n"
    )

    assert result.returncode != 0
    assert "Pull/push first" in result.stderr


def test_unknown_origin_main_fails_closed(tmp_path: Path) -> None:
    repo, commit_a, _ = _repo(tmp_path)
    origin = tmp_path / "origin.git"
    _git(origin, "update-ref", "-d", "refs/heads/main")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    _git(repo, "checkout", "--quiet", "--detach", commit_a)
    result = _run_shell(
        _source(repo) + "pin_deploy_sha\npreflight_branch_synced prod\n",
        GIT_REF=commit_a,
    )

    assert result.returncode != 0
    assert "unknown upstream" in result.stderr


def test_preset_deploy_sha_that_is_not_a_commit_fails(tmp_path: Path) -> None:
    repo, _, _ = _repo(tmp_path)
    missing_sha = "f" * 40
    result = _run_shell(
        _source(repo) + "pin_deploy_sha\n",
        DEPLOY_SHA=missing_sha,
    )

    assert result.returncode != 0
    assert missing_sha in result.stderr
    assert "DEPLOY_SHA" in result.stderr
