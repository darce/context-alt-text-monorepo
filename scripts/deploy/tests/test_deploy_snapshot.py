"""Regression coverage for private DEPLOY_SHA build snapshots."""

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


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    service = repo / "apps/prototype-description-service"
    service.mkdir(parents=True)
    deploy = repo / "scripts/deploy"
    deploy.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.name", "Deploy snapshot test")
    _git(repo, "config", "user.email", "deploy-snapshot@example.invalid")
    (repo / ".gitignore").write_text("out/\n*.onnx.partial\n")
    (service / "Dockerfile").write_text("FROM scratch\n")
    (service / "app.txt").write_text("A\n")
    (deploy / "gpu-snapshot-deployments.conf").write_text("dev\n")
    (deploy / "check-gpu-snapshots.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    _git(repo, "add", ".gitignore", "apps/prototype-description-service", "scripts/deploy")
    _git(repo, "commit", "-qm", "snapshot A")
    return repo, _git(repo, "rev-parse", "HEAD")


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
    return (
        f"source {shlex.quote(str(SCRIPT))}\n"
        f"REPO_ROOT={shlex.quote(str(repo))}\n"
        'SERVICE_DIR="$REPO_ROOT/apps/prototype-description-service"\n'
    )


def _private_tmp(tmp_path: Path) -> Path:
    path = tmp_path / "private-tmp"
    path.mkdir()
    return path


def test_local_build_uses_snapshot_after_live_checkout_changes(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$PWD" > "$DOCKER_PWD_RECORD"\n'
        'find . -type f -print | LC_ALL=C sort > "$DOCKER_FILES_RECORD"\n'
        'cat app.txt > "$DOCKER_APP_RECORD"\n'
    )
    docker.chmod(0o755)
    tmpdir = _private_tmp(tmp_path)
    driver = _source(repo) + r'''
pin_deploy_sha
materialize_deploy_snapshot build
printf 'SNAPSHOT=%s\n' "$DEPLOY_SNAPSHOT_DIR"
printf 'B\n' > "$REPO_ROOT/apps/prototype-description-service/app.txt"
git -C "$REPO_ROOT" add apps/prototype-description-service/app.txt
git -C "$REPO_ROOT" commit -qm 'other session B'
printf 'stray\n' > "$REPO_ROOT/apps/prototype-description-service/stray.txt"
mkdir -p "$REPO_ROOT/apps/prototype-description-service/out"
printf 'ignored\n' > "$REPO_ROOT/apps/prototype-description-service/out/sentinel.txt"
printf 'ignored\n' > "$REPO_ROOT/apps/prototype-description-service/w.onnx.partial"
preflight_docker() { :; }
do_build dev
'''
    result = _run_shell(
        driver,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        TMPDIR=str(tmpdir),
        DOCKER_PWD_RECORD=str(tmp_path / "docker-pwd"),
        DOCKER_FILES_RECORD=str(tmp_path / "docker-files"),
        DOCKER_APP_RECORD=str(tmp_path / "docker-app"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    snapshot_line = next(line for line in result.stdout.splitlines() if line.startswith("SNAPSHOT="))
    snapshot = snapshot_line.removeprefix("SNAPSHOT=")
    docker_pwd = (tmp_path / "docker-pwd").read_text().strip()
    files = (tmp_path / "docker-files").read_text()
    assert docker_pwd.startswith(f"{snapshot}/apps/prototype-description-service")
    assert not docker_pwd.startswith(str(repo))
    assert (tmp_path / "docker-app").read_text() == "A\n"
    assert "stray.txt" not in files
    assert "sentinel.txt" not in files
    assert "w.onnx.partial" not in files


def test_remote_build_rsyncs_snapshot_service_directory(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    tmpdir = _private_tmp(tmp_path)
    args_path = tmp_path / "rsync-args"
    driver = _source(repo) + f'''
pin_deploy_sha
materialize_deploy_snapshot build-remote
printf 'SNAPSHOT=%s\\n' "$DEPLOY_SNAPSHOT_DIR"
preflight_ssh() {{ :; }}
preflight_remote_docker() {{ :; }}
preflight_rsync() {{ :; }}
assert_remote_build_free_space() {{ :; }}
remote_build_phase_timeout() {{ printf '30\\n'; }}
remote_build_cleanup_generation() {{ :; }}
run_with_deadline() {{
  shift 2
  if [[ "$1" == rsync ]]; then
    printf '%s\\n' "$@" > {shlex.quote(str(args_path))}
    return 1
  fi
  return 0
}}
remote_rc=0
do_build_remote dev || remote_rc=$?
test "$remote_rc" = 1
'''
    result = _run_shell(driver, TMPDIR=str(tmpdir))

    assert result.returncode == 0, result.stdout + result.stderr
    snapshot_line = next(line for line in result.stdout.splitlines() if line.startswith("SNAPSHOT="))
    snapshot = snapshot_line.removeprefix("SNAPSHOT=")
    args = args_path.read_text().splitlines()
    assert args[-2] == f"{snapshot}/apps/prototype-description-service/"


def test_snapshot_is_removed_on_success_and_fail_exit(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    tmpdir = _private_tmp(tmp_path)
    for ending, expected_rc in (("exit 0", 0), ('fail "x"', 1)):
        result = _run_shell(
            _source(repo)
            + "pin_deploy_sha\nmaterialize_deploy_snapshot build\n"
            + "printf 'SNAPSHOT=%s\\n' \"$DEPLOY_SNAPSHOT_DIR\"\n"
            + ending
            + "\n",
            TMPDIR=str(tmpdir),
        )

        assert result.returncode == expected_rc, result.stdout + result.stderr
        snapshot_line = next(line for line in result.stdout.splitlines() if line.startswith("SNAPSHOT="))
        assert not Path(snapshot_line.removeprefix("SNAPSHOT=")).exists()


def test_dirty_build_opt_out_uses_live_tree_and_warns(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    result = _run_shell(
        _source(repo)
        + "pin_deploy_sha\nmaterialize_deploy_snapshot build\n"
        + 'printf "SERVICE=%s\\n" "$SERVICE_DIR"\n',
        ACX_ALLOW_DIRTY="1",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SERVICE={repo}/apps/prototype-description-service" in result.stdout
    assert "ACX_ALLOW_DIRTY=1: building the live working tree" in result.stderr


def test_dirty_opt_out_still_snapshots_production_and_promote(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    for command, args in (("deploy", "prod"), ("promote", "dev staging")):
        result = _run_shell(
            _source(repo)
            + f"pin_deploy_sha\nmaterialize_deploy_snapshot {command} {args}\n"
            + '[[ "$SERVICE_DIR" == "$DEPLOY_SNAPSHOT_DIR/apps/prototype-description-service" ]]\n'
            + "printf 'SNAPSHOT=%s\\n' \"$DEPLOY_SNAPSHOT_DIR\"\n",
            ACX_ALLOW_DIRTY="1",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "SNAPSHOT=" in result.stdout


def test_archive_failure_keeps_live_service_dir_and_removes_partial_snapshot(
    tmp_path: Path,
) -> None:
    repo, _ = _repo(tmp_path)
    tmpdir = _private_tmp(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tar = fake_bin / "tar"
    tar.write_text("#!/bin/sh\nexit 1\n")
    tar.chmod(0o755)
    driver = _source(repo) + r'''
pin_deploy_sha
trap 'printf "SERVICE=%s\n" "$SERVICE_DIR"' EXIT
materialize_deploy_snapshot build
'''
    result = _run_shell(
        driver,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        TMPDIR=str(tmpdir),
    )

    assert result.returncode != 0
    assert f"SERVICE={repo}/apps/prototype-description-service" in result.stdout
    assert list(tmpdir.glob("acx-deploy-src.*")) == []


def test_dispatch_materializes_only_shipping_commands_after_sha_pin() -> None:
    source = SCRIPT.read_text()
    dispatch = source.split("#---------------------------------------------------------------- dispatch", 1)[1]
    pin = dispatch.index("pin_deploy_sha")
    materialize = dispatch.index("materialize_deploy_snapshot")
    case = dispatch.index('case "$cmd" in')
    guard_start = dispatch.rfind("if [[", 0, materialize)
    guarded_call = re.match(
        r'if \[\[ (?P<condition>.*?) \]\]; then\s+'
        r'materialize_deploy_snapshot "\$cmd" "\$\{1:-\}"\s+fi',
        dispatch[guard_start:],
        re.DOTALL,
    )

    assert pin < materialize < case
    assert guarded_call is not None
    condition = guarded_call.group("condition")
    for command in ("build", "build-remote", "deploy", "promote", "prepare-producer"):
        assert command in condition
    assert "verify" not in condition


def test_gpu_gate_inputs_come_from_snapshot(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    deploy_dir = repo / "scripts/deploy"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    conf = deploy_dir / "gpu-snapshot-deployments.conf"
    checker = deploy_dir / "check-gpu-snapshots.sh"
    committed_conf = "dev\nstaging\n"
    conf.write_text(committed_conf)
    checker.write_text("#!/usr/bin/env bash\nprintf checker\n")
    _git(repo, "add", "scripts/deploy/gpu-snapshot-deployments.conf", "scripts/deploy/check-gpu-snapshots.sh")
    _git(repo, "commit", "-qm", "snapshot GPU gate inputs")
    tmpdir = _private_tmp(tmp_path)

    result = _run_shell(
        _source(repo)
        + "pin_deploy_sha\nmaterialize_deploy_snapshot build\n"
        + "printf 'prod\\n' > \"$REPO_ROOT/scripts/deploy/gpu-snapshot-deployments.conf\"\n"
        + 'printf "SNAPSHOT_CONF=%s\\n" "$(paste -sd, "$DEPLOY_ASSETS_DIR/gpu-snapshot-deployments.conf")"\n',
        TMPDIR=str(tmpdir),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SNAPSHOT_CONF={committed_conf.replace(chr(10), ',').rstrip(',')}" in result.stdout

    source = SCRIPT.read_text()
    assert '${SCRIPT_DIR}/gpu-snapshot-deployments.conf' not in source
    assert '${SCRIPT_DIR}/check-gpu-snapshots.sh' not in source
