"""Regression coverage for private DEPLOY_SHA build snapshots."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
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


def _direct_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    repo, _ = _repo(tmp_path)
    deploy = repo / "scripts/deploy"
    shutil.copy2(SCRIPT, deploy / "recognition-service.sh")
    (deploy / "lib").mkdir()
    for name in ("ocir-auth.sh", "bounded-remote-build.sh"):
        shutil.copy2(SCRIPT.parent / "lib" / name, deploy / "lib" / name)
    _git(repo, "add", "scripts/deploy")
    _git(repo, "commit", "-qm", "install deploy script")
    pinned_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "ship-ref")

    service_app = repo / "apps/prototype-description-service/app.txt"
    service_app.write_text("LIVE\n")
    _git(repo, "add", "apps/prototype-description-service/app.txt")
    _git(repo, "commit", "-qm", "advance live checkout")
    live_sha = _git(repo, "rev-parse", "HEAD")
    return repo, pinned_sha, live_sha


def _dispatch_tools(tmp_path: Path, *, fail_archive: bool = False) -> tuple[Path, dict[str, str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    git = shutil.which("git")
    tar = shutil.which("tar")
    assert git is not None
    assert tar is not None

    (fake_bin / "git").write_text(
        "#!/usr/bin/env bash\n"
        'command_name="${3:-}"\n'
        'if [[ "$command_name" == "rev-parse" || "$command_name" == "archive" ]]; then\n'
        '  printf "%s\\t" "$command_name" >> "$GIT_EVENT_RECORD"\n'
        '  printf "<%s>" "$@" >> "$GIT_EVENT_RECORD"\n'
        '  printf "\\n" >> "$GIT_EVENT_RECORD"\n'
        "fi\n"
        '"$REAL_GIT_BIN" "$@"\n'
        "status=$?\n"
        'if [[ "$status" == "0" && "$command_name" == "rev-parse" && "${GIT_MUTATED:-0}" != "1" ]]; then\n'
        '  for argument in "$@"; do\n'
        '    if [[ "$argument" == "ship-ref^{commit}" ]]; then\n'
        '      "$REAL_GIT_BIN" -C "$GIT_FIXTURE_ROOT" update-ref refs/heads/ship-ref "$GIT_MUTATE_TO"\n'
        '      printf "mutated\\n" > "$GIT_MUTATED_RECORD"\n'
        '      GIT_MUTATED=1\n'
        "      break\n"
        "    fi\n"
        "  done\n"
        "fi\n"
        'exit "$status"\n'
    )
    (fake_bin / "git").chmod(0o755)

    (fake_bin / "tar").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${FAIL_ARCHIVE:-0}" == "1" ]]; then exit 1; fi\n'
        '"$REAL_TAR_BIN" "$@" || exit $?\n'
        'destination=""\n'
        'while (($#)); do\n'
        '  if [[ "$1" == "-C" ]]; then destination="$2"; shift 2; else shift; fi\n'
        "done\n"
        'if [[ -n "$destination" && -f "$destination/apps/prototype-description-service/app.txt" ]]; then\n'
        '  cp "$destination/apps/prototype-description-service/app.txt" "$ARCHIVE_CONTENT_RECORD"\n'
        "fi\n"
    )
    (fake_bin / "tar").chmod(0o755)

    (fake_bin / "docker").write_text(
        "#!/usr/bin/env bash\n"
        'printf "docker %s\\n" "$*" >> "$EXTERNAL_EVENT_RECORD"\n'
        '[[ "${1:-}" == "info" ]] && exit 0\n'
        "exit 97\n"
    )
    (fake_bin / "docker").chmod(0o755)
    (fake_bin / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        'printf "ssh %s\\n" "$*" >> "$EXTERNAL_EVENT_RECORD"\n'
        "exit 97\n"
    )
    (fake_bin / "ssh").chmod(0o755)

    return fake_bin, {
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "REAL_GIT_BIN": git,
        "REAL_TAR_BIN": tar,
        "GIT_EVENT_RECORD": str(tmp_path / "git-events"),
        "EXTERNAL_EVENT_RECORD": str(tmp_path / "external-events"),
        "ARCHIVE_CONTENT_RECORD": str(tmp_path / "archive-content"),
        "GIT_MUTATED_RECORD": str(tmp_path / "git-ref-mutated"),
        "GIT_FIXTURE_ROOT": "",
        "GIT_MUTATE_TO": "",
        "FAIL_ARCHIVE": "1" if fail_archive else "0",
    }


def _run_direct(
    repo: Path,
    command: str,
    args: tuple[str, ...],
    tools_env: dict[str, str],
    *,
    live_sha: str,
    tmpdir: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("GIT_REF", None)
    env.pop("DEPLOY_SHA", None)
    env.update(tools_env)
    env.update(
        {
            "GIT_REF": "ship-ref",
            "GIT_FIXTURE_ROOT": str(repo),
            "GIT_MUTATE_TO": live_sha,
            "TMPDIR": str(tmpdir),
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(repo / "scripts/deploy/recognition-service.sh"), command, *args],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=20,
    )


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
    driver = (
        _source(repo)
        + r"""
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
"""
    )
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
    driver = (
        _source(repo)
        + f"""
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
"""
    )
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
    driver = (
        _source(repo)
        + r"""
pin_deploy_sha
trap 'printf "SERVICE=%s\n" "$SERVICE_DIR"' EXIT
materialize_deploy_snapshot build
"""
    )
    result = _run_shell(
        driver,
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        TMPDIR=str(tmpdir),
    )

    assert result.returncode != 0
    assert f"SERVICE={repo}/apps/prototype-description-service" in result.stdout
    assert list(tmpdir.glob("acx-deploy-src.*")) == []


def test_dispatch_materializes_only_shipping_commands_after_sha_pin(tmp_path: Path) -> None:
    commands = (
        ("build", ("dev",)),
        ("build-remote", ("dev",)),
        ("deploy", ("dev",)),
        ("promote", ("dev", "staging")),
        ("prepare-producer", ("dev",)),
        ("verify", ("dev",)),
    )
    shipping_commands = {"build", "build-remote", "deploy", "promote", "prepare-producer"}

    for command, args in commands:
        case_dir = tmp_path / command
        case_dir.mkdir()
        repo, pinned_sha, live_sha = _direct_fixture(case_dir)
        tmpdir = _private_tmp(case_dir)
        _, tools_env = _dispatch_tools(case_dir)
        result = _run_direct(
            repo,
            command,
            args,
            tools_env,
            live_sha=live_sha,
            tmpdir=tmpdir,
        )

        assert result.returncode != 0, result.stdout + result.stderr
        external_events = Path(tools_env["EXTERNAL_EVENT_RECORD"]).read_text().splitlines()
        if command == "build":
            assert any(event.startswith("docker build ") for event in external_events)
        else:
            assert any(event.startswith("ssh ") for event in external_events)

        git_events = Path(tools_env["GIT_EVENT_RECORD"]).read_text().splitlines()
        archive_events = [event for event in git_events if event.startswith("archive\t")]
        if command in shipping_commands:
            assert len(archive_events) == 1
            assert f"<{pinned_sha}>" in archive_events[0]
            assert f"<{live_sha}>" not in archive_events[0]
            assert Path(tools_env["ARCHIVE_CONTENT_RECORD"]).read_text() == "A\n"
            assert Path(tools_env["GIT_MUTATED_RECORD"]).exists()
        else:
            assert archive_events == []
            assert any("<ship-ref^{commit}>" in event for event in git_events)
            assert Path(tools_env["GIT_MUTATED_RECORD"]).exists()

    invalid_dir = tmp_path / "invalid-sha"
    invalid_dir.mkdir()
    repo, _, live_sha = _direct_fixture(invalid_dir)
    tmpdir = _private_tmp(invalid_dir)
    _, tools_env = _dispatch_tools(invalid_dir)
    result = _run_direct(
        repo,
        "build",
        ("dev",),
        tools_env,
        live_sha=live_sha,
        tmpdir=tmpdir,
        extra_env={"DEPLOY_SHA": "invalid-sha"},
    )
    assert result.returncode != 0
    assert "DEPLOY_SHA must be a full lowercase 40-character commit SHA" in result.stderr
    assert "invalid-sha" in result.stderr
    assert not Path(tools_env["GIT_EVENT_RECORD"]).exists()
    assert not Path(tools_env["EXTERNAL_EVENT_RECORD"]).exists()

    archive_failure_dir = tmp_path / "archive-failure"
    archive_failure_dir.mkdir()
    repo, _, live_sha = _direct_fixture(archive_failure_dir)
    tmpdir = _private_tmp(archive_failure_dir)
    _, tools_env = _dispatch_tools(archive_failure_dir, fail_archive=True)
    result = _run_direct(
        repo,
        "build",
        ("dev",),
        tools_env,
        live_sha=live_sha,
        tmpdir=tmpdir,
    )
    assert result.returncode != 0
    assert any(
        event.startswith("archive\t")
        for event in Path(tools_env["GIT_EVENT_RECORD"]).read_text().splitlines()
    )
    assert not Path(tools_env["EXTERNAL_EVENT_RECORD"]).exists()


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
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ssh = fake_bin / "ssh"
    ssh.write_text('#!/usr/bin/env bash\ncat > "$SSH_STDIN_RECORD"\n')
    ssh.chmod(0o755)

    result = _run_shell(
        _source(repo)
        + "pin_deploy_sha\nmaterialize_deploy_snapshot build\n"
        + "printf 'LIVE-CONF\\n' > \"$REPO_ROOT/scripts/deploy/gpu-snapshot-deployments.conf\"\n"
        + "printf '#!/usr/bin/env bash\\nprintf live-checker\\n' > "
        + '\"$REPO_ROOT/scripts/deploy/check-gpu-snapshots.sh\"\n'
        + 'printf "SNAPSHOT_CONF=%s\\n" "$(paste -sd, "$DEPLOY_ASSETS_DIR/gpu-snapshot-deployments.conf")"\n'
        + "verify_live_gpu_snapshots dev\n",
        TMPDIR=str(tmpdir),
        PATH=f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        SSH_STDIN_RECORD=str(tmp_path / "ssh-stdin"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SNAPSHOT_CONF={committed_conf.replace(chr(10), ',').rstrip(',')}" in result.stdout
    captured = (tmp_path / "ssh-stdin").read_bytes()
    header, payload = captured.split(b"\n", 1)
    protocol, byte_count, digest = header.decode("ascii").split(" ")
    assert protocol == "ACX_GPU_CHECKER_V1"
    assert int(byte_count) == len(payload)
    assert digest == hashlib.sha256(payload).hexdigest()
    assert payload == b"dev,staging\n#!/usr/bin/env bash\nprintf checker\n"
    assert b"LIVE-CONF" not in payload
    assert b"live-checker" not in payload
