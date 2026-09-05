"""Deploy-pipeline wiring for the GPU lifecycle timers (no live host)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY = REPO_ROOT / "scripts/deploy/recognition-service.sh"
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _run_lifecycle(
    tmp_path: Path,
    *,
    enabled: bool,
    ready_url: str | None,
    dry_run: bool = True,
    verify_rc: int = 0,
    reaper_rc: int = 0,
    flock_rc: int = 0,
    instance_id: str = "ocid1.instance.oc1.us-ashburn-1.aaaa",
    drop_in_paths: str = "",
    mismatched_unit: str | None = None,
    reap_exec_start: str = (
        "/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap "
        "--max-lease-seconds ${MAX_LEASE_SECONDS}"
    ),
    remote_body_mutation: str = "",
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    transport_log = tmp_path / "transport.log"
    expected_systemd = tmp_path / "expected-systemd"
    effective_systemd = tmp_path / "effective-systemd"
    expected_systemd.mkdir()
    effective_systemd.mkdir()
    for unit in (
        "acx-gpu-start.service",
        "acx-gpu-start.timer",
        "acx-gpu-reap.service",
        "acx-gpu-reap.timer",
    ):
        content = f"test fixture for {unit}\n"
        (expected_systemd / unit).write_text(content, encoding="utf-8")
        (effective_systemd / unit).write_text(content, encoding="utf-8")
    lifecycle_env = tmp_path / "gpu-lifecycle.env"
    lifecycle_env.write_text("MAX_LEASE_SECONDS=3600\n", encoding="utf-8")
    fake_host = tmp_path / "host"
    fake_host.mkdir()
    for directory in (
        "opt-acx-gpu",
        "etc-acx",
        "etc-tmpfiles",
        "run-acx",
        "run-acx-write",
        "var-lib-acx-gpu",
    ):
        (fake_host / directory).mkdir()
    _write_executable(
        fake_bin / "ssh",
        r"""#!/usr/bin/env bash
set -euo pipefail
printf 'ssh' >>"$FAKE_TRANSPORT_LOG"
argument_number=0
for argument in "$@"; do
  argument_number=$((argument_number + 1))
  if [ "$argument_number" -lt "$#" ]; then
    printf ' <%s>' "$argument" >>"$FAKE_TRANSPORT_LOG"
  fi
done
printf '\n' >>"$FAKE_TRANSPORT_LOG"
remote_body=${!#}
if [[ "$remote_body" == *"activate_gpu_lifecycle_timers"* ]]; then
  case "${FAKE_REMOTE_BODY_MUTATION:-}" in
    delete_activation_definition)
      remote_body=$(printf '%s\n' "$remote_body" | sed '/^activate_gpu_lifecycle_timers ()/,/^}$/d')
      ;;
    delete_activation_call)
      remote_body=$(printf '%s\n' "$remote_body" | delete-activation-call)
      ;;
  esac
  remote_body=${remote_body//\/opt\/acx-gpu/$FAKE_OPT_ACX_GPU}
  remote_body=${remote_body//\/etc\/systemd\/system/$ACX_EFFECTIVE_SYSTEMD_DIR}
  remote_body=${remote_body//\/etc\/acx/$FAKE_ETC_ACX}
  remote_body=${remote_body//\/etc\/tmpfiles.d/$FAKE_ETC_TMPFILES}
  remote_body=${remote_body//\/run\/acx-write/$FAKE_RUN_ACX_WRITE}
  remote_body=${remote_body//\/run\/acx-gpu/$FAKE_RUN_ACX_GPU}
  remote_body=${remote_body//\/run\/acx/$FAKE_RUN_ACX}
  remote_body=${remote_body//\/var\/lib\/acx-gpu/$FAKE_VAR_LIB_ACX_GPU}
  bash --noprofile --norc -euo pipefail -c "$remote_body"
fi
""",
    )
    _write_executable(
        fake_bin / "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  chown) exit 0 ;;
  *) exec "$@" ;;
esac
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
set -eu
printf 'systemctl' >>"$FAKE_TRANSPORT_LOG"
printf ' <%s>' "$@" >>"$FAKE_TRANSPORT_LOG"
printf '\n' >>"$FAKE_TRANSPORT_LOG"
if [ "$1" = start ] && [ "$2" = acx-gpu-reap.service ]; then
  exit "${FAKE_REAPER_RC:-0}"
fi
if [ "$1" = disable ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  rm -f "$FAKE_START_TIMER_ACTIVE"
  exit 0
fi
if [ "$1" = enable ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  : >"$FAKE_START_TIMER_ACTIVE"
  exit 0
fi
if [ "$1" = stop ] && [ "${2:-}" = acx-gpu-start.service ]; then
  rm -f "$FAKE_START_SERVICE_ACTIVE"
  exit 0
fi
if [ "$1" = show ]; then
  case "$*" in
    *"--property=FragmentPath"*)
      if [ -n "${FAKE_MISMATCHED_UNIT:-}" ] && [ "$2" = "$FAKE_MISMATCHED_UNIT" ]; then
        printf '%s\n' 'stale effective mutation' >>"$ACX_EFFECTIVE_SYSTEMD_DIR/$2"
      fi
      printf '%s/%s\n' "$ACX_EFFECTIVE_SYSTEMD_DIR" "$2"
      ;;
    *"--property=DropInPaths"*) printf '%s\n' "${FAKE_DROP_IN_PATHS:-}" ;;
    *"--property=ExecStart"*)
      printf '%s\n' "$FAKE_REAP_EXEC_START"
      ;;
  esac
  exit 0
fi
if [ "$1" = is-active ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  [ -e "$FAKE_START_TIMER_ACTIVE" ] || exit 3
  exit "${FAKE_VERIFY_RC:-0}"
fi
if [ "$1" = is-active ] && [ "${3:-}" = acx-gpu-start.service ]; then
  [ -e "$FAKE_START_SERVICE_ACTIVE" ]
  exit $?
fi
""",
    )
    _write_executable(
        fake_bin / "flock",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'flock' >>"$FAKE_TRANSPORT_LOG"
printf ' <%s>' "$@" >>"$FAKE_TRANSPORT_LOG"
printf '\n' >>"$FAKE_TRANSPORT_LOG"
exit "${FAKE_FLOCK_RC:-0}"
""",
    )
    _write_executable(
        fake_bin / "delete-activation-call",
        """#!/usr/bin/env python3
import sys

lines = sys.stdin.readlines()
matches = [
    index
    for index, line in enumerate(lines)
    if line.lstrip().startswith("activate_gpu_lifecycle_timers ")
    and "()" not in line
]
if not matches:
    sys.stderr.write("delete-activation-call: activation call not found\\n")
    raise SystemExit(2)
start = matches[-1]
end = start + 1
while end < len(lines) and lines[end - 1].rstrip().endswith("\\\\"):
    end += 1
sys.stdout.writelines(lines[:start] + lines[end:])
""",
    )
    _write_executable(
        fake_bin / "mv",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -Tf|-fT) shift; exec /bin/mv -f "$@" ;;
  *) exec /bin/mv "$@" ;;
esac
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -eu
printf 'scp' >>"$FAKE_TRANSPORT_LOG"
printf ' <%s>' "$@" >>"$FAKE_TRANSPORT_LOG"
printf '\n' >>"$FAKE_TRANSPORT_LOG"
""",
    )

    environment = os.environ.copy()
    for name in ("ACX_DEPLOY_GPU_LIFECYCLE", "ACX_GPU_READY_URL"):
        environment.pop(name, None)
    environment.update(
        {
            "OCI_USER": "ci-user",
            "OCI_HOST": "backend.test",
            "GPU_INSTANCE_ID": instance_id,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_TRANSPORT_LOG": str(transport_log),
            "FAKE_VERIFY_RC": str(verify_rc),
            "FAKE_REAPER_RC": str(reaper_rc),
            "FAKE_FLOCK_RC": str(flock_rc),
            "FAKE_DROP_IN_PATHS": drop_in_paths,
            "FAKE_MISMATCHED_UNIT": mismatched_unit or "",
            "FAKE_REAP_EXEC_START": reap_exec_start,
            "FAKE_REMOTE_BODY_MUTATION": remote_body_mutation,
            "FAKE_START_TIMER_ACTIVE": str(tmp_path / "start-timer.active"),
            "FAKE_START_SERVICE_ACTIVE": str(tmp_path / "start-service.active"),
            "FAKE_OPT_ACX_GPU": str(fake_host / "opt-acx-gpu"),
            "FAKE_ETC_ACX": str(fake_host / "etc-acx"),
            "FAKE_ETC_TMPFILES": str(fake_host / "etc-tmpfiles"),
            "FAKE_RUN_ACX": str(fake_host / "run-acx"),
            "FAKE_RUN_ACX_WRITE": str(fake_host / "run-acx-write"),
            "FAKE_RUN_ACX_GPU": str(fake_host / "run-acx-gpu"),
            "FAKE_VAR_LIB_ACX_GPU": str(fake_host / "var-lib-acx-gpu"),
            "ACX_EXPECTED_SYSTEMD_DIR": str(expected_systemd),
            "ACX_EFFECTIVE_SYSTEMD_DIR": str(effective_systemd),
            "ACX_EXPECTED_ENV_FILE": str(lifecycle_env),
            "ACX_EXPECTED_MAX_LEASE_SECONDS": "3600",
        }
    )
    if enabled:
        environment["ACX_DEPLOY_GPU_LIFECYCLE"] = "1"
    if ready_url is not None:
        environment["ACX_GPU_READY_URL"] = ready_url
    if dry_run:
        environment["ACX_GPU_LIFECYCLE_DRY_RUN"] = "1"

    result = subprocess.run(
        [str(DEPLOY), "gpu-lifecycle"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = transport_log.read_text(encoding="utf-8") if transport_log.exists() else ""
    return result, calls


def test_flag_off_does_not_invoke_installer(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(tmp_path, enabled=False, ready_url=None)

    assert result.returncode == 2, result.stdout + result.stderr
    assert calls == ""
    assert "nothing done" in (result.stdout + result.stderr).lower()


def test_flag_on_requires_explicit_ready_url(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(tmp_path, enabled=True, ready_url=None)

    assert result.returncode != 0
    assert "ACX_GPU_READY_URL is required when ACX_DEPLOY_GPU_LIFECYCLE=1" in result.stderr
    assert calls == ""


@pytest.mark.parametrize(
    "ready_url",
    (
        "http:///health",
        "https://:443/health",
        "http://gpu.test:0/health",
        "http://gpu.test:65536/health",
        "ftp://gpu.test/health",
        "http://user@gpu.test/health",
    ),
)
def test_flag_on_rejects_malformed_ready_url_authority_before_transport(
    tmp_path: Path, ready_url: str
) -> None:
    result, calls = _run_lifecycle(tmp_path, enabled=True, ready_url=ready_url)

    assert result.returncode == 2
    assert "READY_URL" in result.stderr
    assert calls == ""


@pytest.mark.parametrize(
    "instance_id",
    (
        "ocid1.volume.oc1.us-ashburn-1.aaaa",
        "ocid1.instance.oc1.us-ashburn-1.aaaa; touch /tmp/pwned",
        "ocid1.instance.oc1.us-ashburn-1.aaaa$(id)",
        "ocid1.instance.oc1.us-ashburn-1.",
    ),
)
def test_flag_on_rejects_non_instance_ocid_before_transport(
    tmp_path: Path, instance_id: str
) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        instance_id=instance_id,
    )

    assert result.returncode == 2
    assert "ACX_GPU_INSTANCE_ID" in result.stderr
    assert "ocid1.instance.oc1." in result.stderr
    assert calls == ""


def test_installer_rejects_shell_bearing_instance_ocid_before_logging(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            str(INSTALLER),
            "--host",
            "backend.test",
            "--ready-url",
            "http://10.0.1.36:8000/health",
            "--instance-id",
            "ocid1.instance.oc1.us-ashburn-1.aaaa;echo-pwned",
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "GPU instance OCID" in result.stderr
    assert "gpu instance:" not in result.stdout


@pytest.mark.parametrize("max_lease", ("0", "86401", "1h", "-1"))
def test_installer_rejects_unbounded_or_non_numeric_max_lease(max_lease: str) -> None:
    result = subprocess.run(
        [
            str(INSTALLER),
            "--host",
            "backend.test",
            "--ready-url",
            "http://10.0.1.36:8000/health",
            "--instance-id",
            "ocid1.instance.oc1.us-ashburn-1.aaaa",
            "--max-lease-seconds",
            max_lease,
            "--dry-run",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "1 through 86400" in result.stderr


def test_flag_on_invokes_dry_run_without_a_gpu_start_command(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert calls == ""
    assert "gpu-lifecycle-install.sh" in output
    assert "--user ci-user" in output
    assert "--host backend.test" in output
    assert "--dry-run" in output
    invocation = next(line for line in output.splitlines() if "gpu-lifecycle-install.sh" in line)
    assert " instance action start" not in invocation.lower()
    assert " instance launch" not in invocation.lower()
    assert "--max-lease-seconds" in output
    assert "OCID source:  pinned" in output


def test_install_fails_when_timer_verification_finds_an_inactive_timer(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        verify_rc=3,
    )

    assert result.returncode != 0
    assert "acx-gpu-start.timer" in calls
    assert "acx-gpu-reap.timer" in calls
    assert "systemctl <is-enabled>" in calls
    assert "systemctl <is-active>" in calls
    assert "acx-gpu-start.timer is not active" in result.stderr
    assert calls.count("systemctl <start> <acx-gpu-reap.service>") == 2
    assert calls.count("systemctl <disable> <--now> <acx-gpu-start.timer>") == 2
    stop_fences = [
        index
        for index, call in enumerate(calls.splitlines())
        if call == "systemctl <stop> <acx-gpu-start.service>"
    ]
    lock_fences = [
        index for index, call in enumerate(calls.splitlines()) if call.startswith("flock <--wait> <120>")
    ]
    reapers = [
        index
        for index, call in enumerate(calls.splitlines())
        if call == "systemctl <start> <acx-gpu-reap.service>"
    ]
    assert len(stop_fences) == len(lock_fences) == len(reapers) == 2
    assert all(stop < lock < reap for stop, lock, reap in zip(stop_fences, lock_fences, reapers))
    assert "running fail-safe STOP path" in result.stderr
    for ssh_call in (line for line in calls.splitlines() if line.startswith("ssh")):
        assert "<-l> <ci-user> <--> <backend.test>" in ssh_call


def test_cleanup_never_reaps_concurrently_when_start_fence_cannot_quiesce(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        flock_rc=9,
    )

    assert result.returncode != 0
    assert calls.count("systemctl <stop> <acx-gpu-start.service>") == 2
    assert "systemctl <start> <acx-gpu-reap.service>" not in calls
    assert "reaper not invoked concurrently" in result.stderr


def test_effective_unit_drop_in_fails_and_disables_start_timer(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        drop_in_paths="/etc/systemd/system/acx-gpu-reap.service.d/override.conf",
    )

    assert result.returncode != 0
    assert "unexpected effective drop-ins" in result.stderr
    assert "systemctl <disable> <--now> <acx-gpu-start.timer>" in calls


def test_effective_unit_content_mismatch_fails_and_disables_start_timer(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        mismatched_unit="acx-gpu-reap.service",
    )

    assert result.returncode != 0
    assert "effective content does not match this release" in result.stderr
    assert "systemctl <disable> <--now> <acx-gpu-start.timer>" in calls


def test_effective_reaper_must_retain_expected_max_lease_argument(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        reap_exec_start="/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap",
    )

    assert result.returncode != 0
    assert "lacks the max-lease argument" in result.stderr
    assert "systemctl <disable> <--now> <acx-gpu-start.timer>" in calls


def test_installer_own_verifier_fails_loudly_with_fake_systemctl(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    expected_systemd = tmp_path / "expected-systemd"
    effective_systemd = tmp_path / "effective-systemd"
    expected_systemd.mkdir()
    effective_systemd.mkdir()
    for unit in (
        "acx-gpu-start.service",
        "acx-gpu-start.timer",
        "acx-gpu-reap.service",
        "acx-gpu-reap.timer",
    ):
        content = f"test fixture for {unit}\n"
        (expected_systemd / unit).write_text(content, encoding="utf-8")
        (effective_systemd / unit).write_text(content, encoding="utf-8")
    lifecycle_env = tmp_path / "gpu-lifecycle.env"
    lifecycle_env.write_text("MAX_LEASE_SECONDS=3600\n", encoding="utf-8")
    _write_executable(
        fake_bin / "sudo",
        """#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  chown) exit 0 ;;
  *) exec "$@" ;;
esac
""",
    )
    _write_executable(
        fake_bin / "systemctl",
        """#!/usr/bin/env bash
if [ "$1" = show ]; then
  case "$*" in
    *"--property=FragmentPath"*) printf '%s/%s\n' "$ACX_EFFECTIVE_SYSTEMD_DIR" "$2" ;;
    *"--property=DropInPaths"*) printf '\n' ;;
    *"--property=ExecStart"*)
      printf '%s\n' '/usr/bin/python3 --mode reap --max-lease-seconds ${MAX_LEASE_SECONDS}'
      ;;
  esac
  exit 0
fi
if [ "$1" = is-active ]; then
  case "${3:-}" in
    acx-gpu-start.timer|acx-gpu-start.service) exit 3 ;;
  esac
fi
exit 0
""",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{os.environ['PATH']}"
    environment["ACX_EXPECTED_SYSTEMD_DIR"] = str(expected_systemd)
    environment["ACX_EFFECTIVE_SYSTEMD_DIR"] = str(effective_systemd)
    environment["ACX_EXPECTED_ENV_FILE"] = str(lifecycle_env)
    environment["ACX_EXPECTED_MAX_LEASE_SECONDS"] = "3600"
    environment["ACX_GPU_LIFECYCLE_LOCK_PATH"] = str(tmp_path / "state" / "lifecycle.lock")

    result = subprocess.run(
        [str(INSTALLER), "--activate-systemd-only"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "error: acx-gpu-start.timer is not active" in result.stderr


def test_reaper_is_proved_before_start_timer_is_enabled(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    disable = calls.index("systemctl <disable> <--now> <acx-gpu-start.timer>")
    stop_start = calls.index("systemctl <stop> <acx-gpu-start.service>")
    lock_quiesced = calls.index("flock <--wait> <120>")
    reap_proof = calls.index("systemctl <start> <acx-gpu-reap.service>")
    start_timer_enable = calls.index("systemctl <enable> <--now> <acx-gpu-start.timer>")
    assert disable < stop_start < lock_quiesced < reap_proof < start_timer_enable
    assert "systemctl <start> <acx-gpu-start" not in calls
    assert calls.index("systemctl <show> <acx-gpu-reap.service>") < start_timer_enable


def _assert_rendered_activation_contract(result: subprocess.CompletedProcess[str], calls: str) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert "systemctl <start> <acx-gpu-reap.service>" in calls
    assert "systemctl <show> <acx-gpu-reap.service>" in calls
    assert "systemctl <enable> <--now> <acx-gpu-start.timer>" in calls


def _assert_specific_activation_mutant_failure(
    mutation: str,
    result: subprocess.CompletedProcess[str],
    calls: str,
) -> None:
    if mutation == "delete_activation_definition":
        assert result.returncode != 0
        assert "activate_gpu_lifecycle_timers: command not found" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "systemctl <start> <acx-gpu-reap.service>" not in calls
        assert "systemctl <enable> <--now> <acx-gpu-start.timer>" not in calls


@pytest.mark.parametrize(
    "mutation",
    ("delete_activation_definition", "delete_activation_call"),
)
def test_rendered_remote_body_activation_mutants_go_red(tmp_path: Path, mutation: str) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        remote_body_mutation=mutation,
    )

    _assert_specific_activation_mutant_failure(mutation, result, calls)


def test_fail_safe_guard_precedes_live_release_and_effective_artifact_mutations() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    transaction = source[source.index('run_with_deadline "systemd unit installation"') :]

    guard = transaction.index("trap cleanup_gpu_lifecycle_transaction ERR EXIT")
    fence = transaction.index("fence_gpu_lifecycle_start")
    switch = transaction.index("previous_release=\\$(readlink -f /opt/acx-gpu/current")
    artifact_write = transaction.index("sudo tee /etc/systemd/system/acx-gpu-start.service")
    prove_reaper = transaction.index("activate_gpu_lifecycle_timers \\")
    rearm_start = source.index("sudo systemctl enable --now acx-gpu-start.timer")

    assert guard < fence < switch < artifact_write < prove_reaper
    assert "sudo systemctl start acx-gpu-reap.service" in source
    assert source.index("sudo systemctl start acx-gpu-reap.service") < rearm_start
    assert "sudo systemctl stop acx-gpu-start.service" in source
    assert "systemctl is-active --quiet acx-gpu-start.service" in source
    assert "flock --wait 120" in source


def test_every_remote_shell_enables_pipefail() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    remote_shells = source.count('ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail')
    assert remote_shells == 3
    assert 'ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -eu\n' not in source


def test_rendered_install_body_hashes_portably_on_linux_and_macos() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    transaction = source[source.index('run_with_deadline "systemd unit installation"') :]

    assert "command -v sha256sum" in source
    assert "command -v shasum" in source
    assert 'shasum -a 256 "$1"' in source
    assert "sha256_function=$(declare -f sha256_file)" in source
    assert "${sha256_function}" in transaction
    assert "expected_start_service_hash=\\$(sha256_file " in transaction
    assert "expected_reap_timer_hash=\\$(sha256_file " in transaction


def test_installer_preserves_units_with_previous_content_addressed_release() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    assert "previous_release=\\$(readlink -f /opt/acx-gpu/current" in source
    assert "/opt/acx-gpu/previous" in source
    assert "${remote_release}/systemd/acx-gpu-reap.service" in source
    assert "${remote_release}/systemd/acx-gpu-start.timer" in source
    assert "gpu-lifecycle.env" in source
    assert "acx-gpu.conf" in source


def test_failed_synchronous_reaper_never_enables_start_timer(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        reaper_rc=9,
    )

    assert result.returncode != 0
    assert "systemctl <start> <acx-gpu-reap.service>" in calls
    # The verifier is shipped in the rendered script, but no effective-unit
    # query runs after the synchronous reaper fails.
    assert "systemctl <show>" not in calls
