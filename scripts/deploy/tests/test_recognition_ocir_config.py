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
secret_name=
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --secret-name)
      [[ "$#" -ge 2 ]] || { printf '%s\n' 'missing value for --secret-name' >&2; exit 64; }
      secret_name="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
case "$secret_name" in
  OCIR_USERNAME)
    printf '%s' 'tenant/user@example.test' | base64
    ;;
  OCIR_AUTH_TOKEN)
    printf '%s%s' 'deploy-token-' 'byte-exact' | base64
    ;;
  OCIR_CREDENTIAL_GENERATION)
    printf '%s\n' 'ServiceError: NotAuthorizedOrNotFound' >&2
    exit 1
    ;;
  *)
    printf '%s\n' 'unexpected OCI secret name' >&2
    exit 64
    ;;
esac
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
        f"DOCKER_CONFIG={config_dir} exec docker push iad.ocir.io/test/image:sha"
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
    assert f"DOCKER_CONFIG={config_path} exec docker push iad.ocir.io/test/image:sha" in commands
    assert f"rm -rf -- {config_path}" in commands
    assert "acx-ocir-reaper" in commands
    assert "ConnectTimeout=5" in commands
    assert "ServerAliveInterval=15" in commands
    assert not config_path.exists()


def test_all_remote_registry_commands_carry_the_deploy_config() -> None:
    source = SCRIPT.read_text()
    assert "remote_docker_with_config()" in source
    assert 'config_q="$(remote_quote "${ACX_DEPLOY_OCIR_CONFIG_DIR}")"' in source
    assert '_pull_ref_remote "${image}"' in source
    assert '_pull_ref "${IMAGE_BASE}:${from_tag}"' in source
    assert 'remote_docker_with_config push "${rollback_ref}"' in source
    assert "DOCKER_CONFIG='${ACX_DEPLOY_OCIR_CONFIG_DIR}'" not in source


def test_hostile_tmpdir_is_rejected_before_any_remote_command(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sentinel = tmp_path / "PWNED"
    hostile = tmp_path / "q';touch PWNED;#"
    hostile.mkdir()
    _executable(
        bin_dir / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
last=
for arg in "$@"; do last="$arg"; done
bash -c "$last"
""",
    )
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "TMPDIR": str(hostile)})
    result = subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; init_remote_ocir_docker_config'],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "TMPDIR must be an existing absolute directory" in result.stderr
    assert not sentinel.exists()


def test_config_initialization_does_not_leak_umask(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["TMPDIR"] = str(tmp_path)
    command = (
        f'umask 0022; source "{SCRIPT}"; before="$(umask)"; '
        'init_deploy_ocir_docker_config; after="$(umask)"; '
        'cleanup_deploy_ocir_docker_config; printf "%s %s" "$before" "$after"'
    )
    result = subprocess.run(["/bin/bash", "-c", command], env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("0022 0022")


def test_stalled_push_has_deadline_and_unknown_outcome(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "docker", "#!/usr/bin/env bash\nexec sleep 30\n")
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "ACX_PUSH_TIMEOUT": "1"})
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'source "{SCRIPT}"; REMOTE_BUILD=0; _push_ref iad.ocir.io/test/image:sha',
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=6,
        check=False,
    )
    assert result.returncode == 124
    assert "outcome UNKNOWN" in result.stderr


def test_digest_mismatch_fails_environment_tag_promotion(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    expected = "a" * 64
    wrong = "b" * 64
    _executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "image inspect" ]]; then
  printf '%s\\n' "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:{wrong}"
fi
""",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    command = f'source "{SCRIPT}"; REMOTE_BUILD=0; do_push_tag latest "${{IMAGE_BASE}}@sha256:{expected}"'
    result = subprocess.run(["/bin/bash", "-c", command], env=env, text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "DIGEST MISMATCH" in result.stderr


def test_rollback_is_captured_before_remote_build_and_used_on_failures() -> None:
    source = SCRIPT.read_text()
    deploy = source[
        source.index("do_deploy() {") : source.index(
            "#---------------------------------------------------------------- promote"
        )
    ]
    assert deploy.index('preserve_rollback_tag "$env"') < deploy.index('do_build_remote "$tag"')
    assert 'restore_env_tag_to_rollback "$env" 0' in deploy
    # Executable phase tests pin when runtime recovery is required.
    assert 'restore_env_tag_to_rollback "$env" "${restart_runtime}"' in deploy
    assert 'promote_gate "$env" "${ACX_CANDIDATE_DIGEST_REF}"' in deploy


def test_previous_serving_digest_is_published_as_rollback(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    records = tmp_path / "docker.commands"
    bin_dir.mkdir()
    digest = "c" * 64
    image_id = f"sha256:{'b' * 64}"
    _executable(
        bin_dir / "ssh",
        f"""#!/usr/bin/env bash
set -euo pipefail
last=
for arg in "$@"; do last="$arg"; done
if [[ "$last" == *".Config.Image"* ]]; then
  printf '%s\n' 'iad.ocir.io/idu2kqqe2jxy/acx-backend:latest'
  exit 0
elif [[ "$last" == *".Image"* ]]; then
  printf '%s\n' '{image_id}'
  exit 0
fi
bash -c "$last"
""",
    )
    _executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$OCIR_TEST_DOCKER_RECORD"
if [[ "$*" == *"{{.Id}}"* ]]; then
  printf '%s\\n' "{image_id}"
elif [[ "$1 $2" == "image inspect" ]]; then
  printf '%s\\n' "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:{digest}"
fi
""",
    )
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "OCIR_TEST_DOCKER_RECORD": str(records)})
    command = (
        f'source "{SCRIPT}"; ACX_DEPLOY_OCIR_CONFIG_DIR=/tmp/acx-test-config; '
        'preserve_rollback_tag prod; printf "%s %s" "$ACX_ROLLBACK_DIGEST_REF" "$ACX_ROLLBACK_TAG"'
    )
    result = subprocess.run(["/bin/bash", "-c", command], env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert f"@sha256:{digest} rollback-{digest[:12]}" in result.stdout
    commands = records.read_text()
    assert f"tag {image_id} " in commands
    assert f"push iad.ocir.io/idu2kqqe2jxy/acx-backend:rollback-{digest[:12]}" in commands


def test_repair_failure_recovery_restores_vm_and_registry_tag(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    records = tmp_path / "docker.commands"
    bin_dir.mkdir()
    digest = "d" * 64
    _executable(
        bin_dir / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
last=
for arg in "$@"; do last="$arg"; done
bash -c "$last"
""",
    )
    _executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$OCIR_TEST_DOCKER_RECORD"
if [[ "$1 $2" == "image inspect" ]]; then
  printf '%s\n' "iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:{digest}"
fi
""",
    )
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "OCIR_TEST_DOCKER_RECORD": str(records)})
    remote_dir = tmp_path / "remote" / "prod"
    remote_dir.mkdir(parents=True)
    command = (
        f'source "{SCRIPT}"; ACX_DEPLOY_OCIR_CONFIG_DIR=/tmp/acx-test-config; '
        f'env_to_remote_dir() {{ printf "%s" "{remote_dir}"; }}; '
        f'ACX_ROLLBACK_DIGEST_REF="${{IMAGE_BASE}}@sha256:{digest}"; '
        "restore_env_tag_to_rollback prod 0"
    )
    result = subprocess.run(["/bin/bash", "-c", command], env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    commands = records.read_text()
    assert (
        f"tag iad.ocir.io/idu2kqqe2jxy/acx-backend@sha256:{digest} iad.ocir.io/idu2kqqe2jxy/acx-backend:latest"
        in commands
    )
    assert "push iad.ocir.io/idu2kqqe2jxy/acx-backend:latest" in commands
    assert "compose -f docker-compose.env.yml -f docker-compose.admin.yml pull api" not in commands


def test_rollback_digest_comes_from_the_running_container(tmp_path: Path) -> None:
    records = tmp_path / "commands"
    digest = "e" * 64
    image_id = f"sha256:{'f' * 64}"
    old_repo = "iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm"
    command = f'''
source "{SCRIPT}"
ACX_DEPLOY_OCIR_CONFIG_DIR=/tmp/acx-test-config
read_running_api_image_id() {{ printf '%s\\n' '{image_id}'; }}
read_running_api_image() {{ printf '%s\\n' '{old_repo}:latest'; }}
remote_docker_with_config() {{
  printf '%s\\n' "$*" >>"{records}"
  if [[ "$*" == *"{{{{.Id}}}}"* ]]; then
    printf '%s\\n' '{image_id}'
  elif [[ "$1 $2 ${{3:-}}" == "image inspect --format" ]]; then
    printf '%s\\n' '{old_repo}@sha256:{digest}'
  fi
}}
preserve_rollback_tag prod
printf '%s\\n' "$ACX_ROLLBACK_DIGEST_REF $ACX_ROLLBACK_IMAGE_BASE"
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert f"{old_repo}@sha256:{digest} {old_repo}" in result.stdout
    commands = records.read_text().splitlines()
    assert commands[0].endswith(image_id)
    assert all("acx-backend:latest" not in item for item in commands)
    assert f"tag {image_id} {old_repo}:rollback-{digest[:12]}" in commands
    assert f"push {old_repo}:rollback-{digest[:12]}" in commands


@pytest.mark.parametrize("remote_build", ["0", "1"])
def test_stalled_pull_has_deadline_in_both_build_modes(tmp_path: Path, remote_build: str) -> None:
    command = f'''
source "{SCRIPT}"
REMOTE_BUILD={remote_build}
ACX_PULL_TIMEOUT=1
docker() {{ sleep 30; }}
remote_docker_with_config() {{ sleep 30; }}
_pull_ref iad.ocir.io/test/image@sha256:{"a" * 64}
'''
    result = subprocess.run(
        ["/bin/bash", "-c", command],
        text=True,
        capture_output=True,
        timeout=6,
        check=False,
    )
    assert result.returncode == 124
    assert "outcome UNKNOWN" in result.stderr


def test_deploy_records_transaction_order_and_pins_restart_digest(tmp_path: Path) -> None:
    records = tmp_path / "sequence"
    digest = f"${{IMAGE_BASE}}@sha256:{'a' * 64}"
    command = f'''
source "{SCRIPT}"
REMOTE_BUILD=1
record() {{ printf '%s\\n' "$*" >>"{records}"; }}
init_deploy_ocir_docker_config() {{ :; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_git_clean() {{ :; }}
preflight_branch_synced() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
preserve_rollback_tag() {{ record preserve "$@"; }}
do_build_remote() {{ record build "$@"; }}
do_push_sha() {{ ACX_CANDIDATE_DIGEST_REF="{digest}"; record push-sha "$ACX_CANDIDATE_DIGEST_REF"; }}
promote_gate() {{ record smoke "$@"; }}
do_push_tag() {{ record promote "$@"; }}
do_restart() {{ record restart "$@"; }}
do_verify() {{ record verify "$@"; }}
do_deploy dev
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    image_base = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
    digest_ref = f"{image_base}@sha256:{'a' * 64}"
    assert records.read_text().splitlines() == [
        "preserve dev",
        "build dev",
        f"push-sha {digest_ref}",
        f"smoke dev {digest_ref}",
        f"promote dev {digest_ref}",
        f"restart dev {digest_ref}",
        "verify dev",
    ]


def test_restore_failure_is_propagated_and_never_claimed_success(tmp_path: Path) -> None:
    records = tmp_path / "commands"
    digest = "d" * 64
    command = f'''
source "{SCRIPT}"
ACX_DEPLOY_OCIR_CONFIG_DIR=/tmp/acx-test-config
ACX_ROLLBACK_IMAGE_BASE="$IMAGE_BASE"
ACX_ROLLBACK_DIGEST_REF="$IMAGE_BASE@sha256:{digest}"
remote_docker_with_config() {{
  printf '%s\\n' "$*" >>"{records}"
  [[ "$1" != push ]]
}}
if restore_env_tag_to_rollback prod 0; then
  exit 0
else
  exit $?
fi
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)
    assert result.returncode != 0
    assert "Restored" not in result.stdout


def test_single_attempt_verify_does_not_sleep_after_terminal_failure(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sleep_record = tmp_path / "sleep-called"
    _executable(bin_dir / "curl", "#!/usr/bin/env bash\necho immediate-401 >&2\nexit 22\n")
    _executable(
        bin_dir / "sleep",
        '#!/usr/bin/env bash\nprintf called >"$OCIR_TEST_SLEEP_RECORD"\n',
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ACX_VERIFY_ATTEMPTS": "1",
            "ACX_VERIFY_SLEEP": "5",
            "OCIR_TEST_SLEEP_RECORD": str(sleep_record),
        }
    )
    result = subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; do_verify dev'],
        env=env,
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert result.returncode == 1
    assert "immediate-401" in result.stderr
    assert not sleep_record.exists()


def test_verify_accepts_unhealthy_health_body_and_compares_identity() -> None:
    expected_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=SCRIPT.parents[2],
        text=True,
    ).strip()
    body = (
        '{"status":"unhealthy","commit_sha":"'
        f"{expected_sha}"
        '","image_variant":"recognition","database":{"status":"unhealthy"}}'
    )
    command = f'''
source "{SCRIPT}"
ACX_VERIFY_ATTEMPTS=1
ACX_VERIFY_SLEEP=0
ACX_VERIFY_EXPECT_LOCAL=1
curl() {{ printf '%s\\n503' '{body}'; }}
verify_running_image_matches_deployed() {{ :; }}
verify_live_gpu_snapshots() {{ :; }}
do_verify dev
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "reports unhealthy (database)" in result.stderr
    assert "Verified: dev runs" in result.stdout


def test_status_prints_unhealthy_for_reachable_503_health_body() -> None:
    body = '{"status":"unhealthy","commit_sha":"deadbeef","image_variant":"recognition"}'
    command = f'''
source "{SCRIPT}"
curl() {{ printf '%s\\n503' '{body}'; }}
do_status
'''
    result = subprocess.run(["/bin/bash", "-c", command], text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 4
    assert all("unhealthy" in line for line in lines)
    assert all("unreachable" not in line for line in lines)
