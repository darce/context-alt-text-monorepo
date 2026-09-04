"""Executable regressions for deploy-scoped OCIR Docker credentials."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _fake_tools(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    records = tmp_path / "records"
    bin_dir.mkdir()
    records.mkdir()
    _executable(
        bin_dir / "oci",
        """#!/usr/bin/env bash
set -euo pipefail
count_file="${OCIR_TEST_RECORD_DIR}/oci.count"
count=0
[[ ! -f "$count_file" ]] || count="$(<"$count_file")"
count=$((count + 1))
printf '%s' "$count" >"$count_file"
if [[ "$count" -eq 1 ]]; then
  printf '%s' 'tenant/user@example.test' | base64
else
  printf '%s%s' 'deploy-token-' 'byte-exact' | base64
fi
""",
    )
    _executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
: "${DOCKER_CONFIG:?}"
: "${OCIR_TEST_RECORD_DIR:?}"
case "$1" in
  login)
    token="$(cat)"
    mkdir -p "$DOCKER_CONFIG"
    printf '{"auths":{"test":{"auth":"%s"}}}' "$token" >"$DOCKER_CONFIG/config.json"
    printf '%s' "$DOCKER_CONFIG" >"$OCIR_TEST_RECORD_DIR/login.path"
    cksum "$DOCKER_CONFIG/config.json" >"$OCIR_TEST_RECORD_DIR/login.cksum"
    ;;
  push)
    printf '%s' "$DOCKER_CONFIG" >"$OCIR_TEST_RECORD_DIR/push.path"
    [[ -f "$DOCKER_CONFIG/config.json" ]]
    cksum "$DOCKER_CONFIG/config.json" >"$OCIR_TEST_RECORD_DIR/push.cksum"
    [[ "${OCIR_TEST_PUSH_FAIL:-0}" != 1 ]] || exit 41
    ;;
  *) exit 64 ;;
esac
""",
    )
    return bin_dir, records


def _run_local_push(tmp_path: Path, *, fail_push: bool) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir, records = _fake_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMPDIR": str(tmp_path),
            "OCIR_TEST_RECORD_DIR": str(records),
            "ACX_LOCAL_OCI_BIN": "oci",
            "REMOTE_BUILD": "0",
            "OCIR_TEST_PUSH_FAIL": "1" if fail_push else "0",
        }
    )
    command = f'source "{SCRIPT}"; preflight_ocir_auth; _push_ref iad.ocir.io/test/image:sha'
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, records


def _assert_shared_config_was_cleaned(tmp_path: Path, records: Path) -> None:
    login_path = Path((records / "login.path").read_text())
    push_path = Path((records / "push.path").read_text())
    assert push_path == login_path
    assert (records / "push.cksum").read_text() == (records / "login.cksum").read_text()
    assert not login_path.exists()
    assert not list(tmp_path.glob("acx-ocir-deploy.*/config.json"))
    survivors = [
        path for path in tmp_path.rglob("*") if path.is_file() and b"deploy-token-byte-exact" in path.read_bytes()
    ]
    assert survivors == []


def test_local_push_uses_login_config_and_success_cleans_it(tmp_path: Path) -> None:
    result, records = _run_local_push(tmp_path, fail_push=False)
    assert result.returncode == 0, result.stderr
    _assert_shared_config_was_cleaned(tmp_path, records)


def test_failed_local_push_still_cleans_login_config(tmp_path: Path) -> None:
    result, records = _run_local_push(tmp_path, fail_push=True)
    assert result.returncode == 41, result.stderr
    _assert_shared_config_was_cleaned(tmp_path, records)


def test_signal_exit_cleans_login_config(tmp_path: Path) -> None:
    bin_dir, records = _fake_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMPDIR": str(tmp_path),
            "OCIR_TEST_RECORD_DIR": str(records),
            "ACX_LOCAL_OCI_BIN": "oci",
        }
    )
    command = f'source "{SCRIPT}"; preflight_ocir_auth; kill -TERM $$'
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    config_path = Path((records / "login.path").read_text())
    assert result.returncode == 143, result.stderr
    assert not config_path.exists()
    assert not list(tmp_path.glob("acx-ocir-deploy.*/config.json"))


def test_remote_push_command_explicitly_carries_config(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    records = tmp_path / "records"
    bin_dir.mkdir()
    records.mkdir()
    _executable(
        bin_dir / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
last=
for arg in "$@"; do last="$arg"; done
printf '%s' "$last" >"$OCIR_TEST_RECORD_DIR/ssh.command"
""",
    )
    config_dir = "/tmp/acx-ocir-deploy.test-safe"
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "OCIR_TEST_RECORD_DIR": str(records)})
    command = (
        f'source "{SCRIPT}"; REMOTE_BUILD=1; '
        f'ACX_DEPLOY_OCIR_CONFIG_DIR="{config_dir}"; '
        "_push_ref iad.ocir.io/test/image:sha"
    )
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (records / "ssh.command").read_text() == (
        f"DOCKER_CONFIG='{config_dir}' docker push iad.ocir.io/test/image:sha"
    )


@pytest.mark.parametrize(("fail_push", "expected_rc"), [(False, 0), (True, 42)])
def test_remote_push_issues_bounded_remote_cleanup(tmp_path: Path, fail_push: bool, expected_rc: int) -> None:
    bin_dir = tmp_path / "bin"
    records = tmp_path / "records"
    bin_dir.mkdir()
    records.mkdir()
    _executable(
        bin_dir / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
last=
for arg in "$@"; do last="$arg"; done
printf 'ARGS:%s\n' "$*" >>"$OCIR_TEST_RECORD_DIR/ssh.commands"
printf '%s\n' "$last" >>"$OCIR_TEST_RECORD_DIR/ssh.commands"
case "$last" in
  *"docker push"*) [[ "${OCIR_TEST_PUSH_FAIL:-0}" != 1 ]] || exit 42 ;;
esac
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMPDIR": str(tmp_path),
            "OCIR_TEST_RECORD_DIR": str(records),
            "REMOTE_BUILD": "1",
            "OCIR_TEST_PUSH_FAIL": "1" if fail_push else "0",
        }
    )
    command = (
        f'source "{SCRIPT}"; preflight_remote_ocir_auth; '
        'printf "%s" "$ACX_DEPLOY_OCIR_CONFIG_DIR" >"$OCIR_TEST_RECORD_DIR/config.path"; '
        "_push_ref iad.ocir.io/test/image:sha"
    )
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    config_path = Path((records / "config.path").read_text())
    commands = (records / "ssh.commands").read_text()
    assert result.returncode == expected_rc, result.stderr
    assert f"DOCKER_CONFIG='{config_path}' docker push iad.ocir.io/test/image:sha" in commands
    assert f"rm -rf -- '{config_path}'" in commands
    assert "ConnectTimeout=5" in commands
    assert not config_path.exists()


def test_all_remote_registry_commands_carry_the_deploy_config() -> None:
    source = SCRIPT.read_text()
    remote_registry_commands = [
        line.strip() for line in source.splitlines() if 'ssh -l "${OCI_USER}"' in line or '"DOCKER_CONFIG=' in line
    ]
    joined = "\n".join(remote_registry_commands)
    assert "DOCKER_CONFIG='${ACX_DEPLOY_OCIR_CONFIG_DIR}' docker push ${ref}" in joined
    assert "DOCKER_CONFIG='${ACX_DEPLOY_OCIR_CONFIG_DIR}' docker pull ${image}" in joined
    assert "DOCKER_CONFIG='${ACX_DEPLOY_OCIR_CONFIG_DIR}' docker pull ${IMAGE_BASE}:${from_tag}" in joined
    assert '_push_ref "${IMAGE_BASE}:${to_tag}"' in source
    assert "DOCKER_CONFIG='${ACX_DEPLOY_OCIR_CONFIG_DIR}' docker compose ${compose_files} pull api" in joined


def test_pushes_have_a_validated_deadline_and_remote_keepalives() -> None:
    source = SCRIPT.read_text()
    push = source.split("_push_ref()", 1)[1].split("do_push_sha()", 1)[0]
    assert 'run_with_timeout "remote docker push ${ref}" "${PUSH_TIMEOUT}"' in push
    assert 'run_with_timeout "local docker push ${ref}" "${PUSH_TIMEOUT}"' in push
    assert "ServerAliveInterval=10" in push
    assert "ServerAliveCountMax=3" in push
    assert "ACX_PUSH_TIMEOUT must be a positive integer" in source


def test_remote_build_is_immutable_and_resource_isolated() -> None:
    source = SCRIPT.read_text()
    build = source.split("do_build_remote()", 1)[1].split("_push_ref()", 1)[0]
    assert "docker buildx build" in build
    assert "--builder '${REMOTE_BUILDER_NAME}' --load" in build
    assert "cpu-quota=150000" in source
    assert "memory=4g" in source
    assert 'if [[ "${2:-}" != "--immutable-only" ]]' in build
    assert "-t ${IMAGE_BASE}:${sha}" in build
    deploy = source.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert 'do_build_remote "$tag" --immutable-only' in deploy
    assert 'do_build "$tag" --immutable-only' in deploy


def test_failed_cutovers_restore_restart_and_verify_the_rollback() -> None:
    source = SCRIPT.read_text()
    rollback = source.split("rollback_failed_cutover()", 1)[1].split("abort_after_failed_cutover()", 1)[0]
    assert "${ACX_ROLLBACK_REF}" in rollback
    assert "restore_prior_image_repo_env" in rollback
    assert 'do_restart "$env"' in rollback
    assert 'verify_rollback_health "$env"' in rollback
    for body in (
        source.split("do_deploy()", 1)[1].split("do_promote()", 1)[0],
        source.split("do_promote()", 1)[1].split("do_verify()", 1)[0],
    ):
        assert "abort_after_failed_cutover" in body
        assert "ACX_VERIFY_OPTIONAL" not in body
