"""Deploy-pipeline wiring for the GPU lifecycle timers (no live host)."""

from __future__ import annotations

import os
import re
import subprocess
import time
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
    previous_release: bool = False,
    fence_failure: str = "",
    fence_load_state: str = "loaded",
    remote_timeout: int = 20,
    fixture_timeout: int = 30,
    remote_stall: int = 0,
    reap_interval: str = "2min",
    snapshot_kind: str = "complete",
    snapshot_copy_failure: bool = False,
    empty_rollback_artifact: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    transport_log = tmp_path / "transport.log"
    expected_systemd = tmp_path / "expected-systemd"
    effective_systemd = tmp_path / "effective-systemd"
    expected_systemd.mkdir(exist_ok=True)
    effective_systemd.mkdir(exist_ok=True)
    # Fresh hosts have no lifecycle units; upgrades retain the old units.
    for unit in (() if not previous_release else (
        "acx-gpu-start.service",
        "acx-gpu-start.timer",
        "acx-gpu-reap.service",
        "acx-gpu-reap.timer",
    )):
        content = f"test fixture for {unit}\n"
        (expected_systemd / unit).write_text(content, encoding="utf-8")
        (effective_systemd / unit).write_text(content, encoding="utf-8")
    lifecycle_env = tmp_path / "gpu-lifecycle.env"
    lifecycle_env.write_text("MAX_LEASE_SECONDS=3600\n", encoding="utf-8")
    fake_host = tmp_path / "host"
    fake_host.mkdir(exist_ok=True)
    for directory in (
        "opt-acx-gpu",
        "etc-acx",
        "etc-tmpfiles",
        "run-acx",
        "run-acx-write",
        "var-lib-acx-gpu",
    ):
        (fake_host / directory).mkdir(exist_ok=True)
    if previous_release and not (fake_host / "opt-acx-gpu/current").is_symlink():
        release_root = fake_host / "opt-acx-gpu"
        old_release = release_root / "old release"
        old_release.mkdir()
        (fake_host / "etc-acx/gpu-lifecycle.env").write_text("MAX_LEASE_SECONDS=3600\n")
        (fake_host / "etc-tmpfiles/acx-gpu.conf").write_text("# old tmpfiles\n")
        if snapshot_kind != "missing":
            snapshot = old_release / "systemd"
            snapshot.mkdir()
            (snapshot / "gpu-lifecycle.env").write_text("MAX_LEASE_SECONDS=3600\n")
            if snapshot_kind == "complete":
                (snapshot / "acx-gpu.conf").write_text("# old tmpfiles\n")
                for unit in effective_systemd.iterdir():
                    (snapshot / unit.name).write_text(unit.read_text())
        (release_root / "older release").mkdir()
        (release_root / "current").symlink_to("old release", target_is_directory=True)
        (release_root / "previous").symlink_to("older release", target_is_directory=True)
        if empty_rollback_artifact is not None:
            if snapshot_kind == "missing":
                artifact_dir = {
                    "gpu-lifecycle.env": fake_host / "etc-acx",
                    "acx-gpu.conf": fake_host / "etc-tmpfiles",
                }.get(empty_rollback_artifact, effective_systemd)
            else:
                artifact_dir = old_release / "systemd"
            (artifact_dir / empty_rollback_artifact).write_text("")
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
printf '%s\n' "$remote_body" >>"$FAKE_REMOTE_BODY_LOG"
if [[ "$remote_body" == *"activate_gpu_lifecycle_timers"* ]]; then
  # A descendant holds the captured pipes, just as a stalled remote body does.
  if [ "${FAKE_REMOTE_STALL:-0}" -gt 0 ]; then
    bash -c 'trap "" TERM; sleep "$FAKE_REMOTE_STALL"' &
    wait "$!"
  fi
  case "${FAKE_REMOTE_BODY_MUTATION:-}" in
    delete_activation_definition)
      remote_body=$(printf '%s\n' "$remote_body" | sed '/^activate_gpu_lifecycle_timers ()/,/^}$/d')
      ;;
    delete_activation_call)
      remote_body=$(printf '%s\n' "$remote_body" | delete-activation-call)
      ;;
  esac
  # Bash 3.2 bulk substitutions are extremely slow in UTF-8 locales. Rewrite
  # in one Python pass, matching longer paths before their shared prefixes.
  remote_body=$(printf '%s\n' "$remote_body" | python3 -c '
import os
import re
import sys

paths = {
    "/opt/acx-gpu": "FAKE_OPT_ACX_GPU",
    "/etc/systemd/system": "ACX_EFFECTIVE_SYSTEMD_DIR",
    "/etc/acx": "FAKE_ETC_ACX",
    "/etc/tmpfiles.d": "FAKE_ETC_TMPFILES",
    "/run/acx-write": "FAKE_RUN_ACX_WRITE",
    "/run/acx-gpu": "FAKE_RUN_ACX_GPU",
    "/run/acx": "FAKE_RUN_ACX",
    "/var/lib/acx-gpu": "FAKE_VAR_LIB_ACX_GPU",
}
pattern = "|".join(re.escape(path) for path in sorted(paths, key=len, reverse=True))
sys.stdout.write(re.sub(pattern, lambda match: os.environ[paths[match[0]]], sys.stdin.read()))
')
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
  cp)
    if [ "${FAKE_SNAPSHOT_COPY_FAILURE:-0}" = 1 ] && [[ "$2" == */acx-gpu.conf ]]; then
      echo 'injected snapshot copy failure' >&2
      exit 74
    fi
    exec "$@"
    ;;
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
  [ "${FAKE_FENCE_FAILURE:-}" != timer ] || exit 1
  [ -f "$ACX_EFFECTIVE_SYSTEMD_DIR/acx-gpu-start.timer" ] || exit 1
  rm -f "$FAKE_START_TIMER_ACTIVE"
  exit 0
fi
if [ "$1" = enable ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  : >"$FAKE_START_TIMER_ACTIVE"
  exit 0
fi
if [ "$1" = stop ] && [ "${2:-}" = acx-gpu-start.service ]; then
  [ "${FAKE_FENCE_FAILURE:-}" != service ] || exit 1
  [ -f "$ACX_EFFECTIVE_SYSTEMD_DIR/acx-gpu-start.service" ] || exit 5
  rm -f "$FAKE_START_SERVICE_ACTIVE"
  exit 0
fi
if [ "$1" = show ]; then
  case "$*" in
    *"--property=LoadState"*)
      if [ -n "${FAKE_FENCE_FAILURE:-}" ]; then
        [ "$FAKE_FENCE_LOAD_STATE" != query-error ] || exit 1
        printf '%s\n' "$FAKE_FENCE_LOAD_STATE"
      elif [ -f "$ACX_EFFECTIVE_SYSTEMD_DIR/$2" ]; then
        printf 'loaded\n'
      else
        printf 'not-found\n'
      fi
      ;;
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
            # A stalled fake transport must fail quickly on every host.
            "REMOTE_COMMAND_TIMEOUT_SECONDS": str(remote_timeout),
            "FAKE_REMOTE_STALL": str(remote_stall),
            "REAP_INTERVAL": reap_interval,
            "FAKE_SNAPSHOT_COPY_FAILURE": "1" if snapshot_copy_failure else "0",
            "FAKE_FENCE_FAILURE": fence_failure,
            "FAKE_FENCE_LOAD_STATE": fence_load_state,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_TRANSPORT_LOG": str(transport_log),
            "FAKE_REMOTE_BODY_LOG": str(tmp_path / "remote-body.sh"),
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
        timeout=fixture_timeout,
    )
    assert not re.search(r"error: .* exceeded \d+s", result.stderr), result.stderr
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
    assert "exceeded 20s" not in result.stderr
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


def test_remote_body_stall_reaches_timeout_rejection(tmp_path: Path) -> None:
    started = time.monotonic()
    # Must reach the fixture's assertion, rather than hang on descendant pipes
    # or mistake a deadline failure for the expected inactive-timer failure.
    with pytest.raises(AssertionError, match="systemd unit installation exceeded 1s"):
        _run_lifecycle(
            tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
            dry_run=False, verify_rc=3, remote_timeout=1, fixture_timeout=8,
            remote_stall=30,
        )
    assert time.monotonic() - started < 8


@pytest.mark.parametrize("unit", ("timer", "service"))
@pytest.mark.parametrize("load_state", ("loaded", "error", "", "query-error"))
def test_fence_failure_requires_confirmed_absent_unit(
    tmp_path: Path, unit: str, load_state: str,
) -> None:
    result, calls = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True, fence_failure=unit,
        fence_load_state=load_state,
    )
    assert result.returncode != 0
    assert "could not fence START during cleanup" in result.stderr
    assert "systemctl <start> <acx-gpu-reap.service>" not in calls
    assert "systemctl <enable> <--now> <acx-gpu-start.timer>" not in calls
    assert (tmp_path / "host/opt-acx-gpu/current").resolve().name == "old release"


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
    _write_executable(fake_bin / "flock", "#!/usr/bin/env bash\nexit 0\n")

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
    # Neither unit existed when the initial fence ran on this fresh host.
    assert "systemctl <show> <acx-gpu-start.timer> <--property=LoadState>" in calls
    assert "systemctl <show> <acx-gpu-start.service> <--property=LoadState>" in calls
    lock_quiesced = calls.index("flock <--wait> <120>")
    reap_proof = calls.index("systemctl <start> <acx-gpu-reap.service>")
    start_timer_enable = calls.index("systemctl <enable> <--now> <acx-gpu-start.timer>")
    assert disable < stop_start < lock_quiesced < reap_proof < start_timer_enable
    assert "systemctl <start> <acx-gpu-start" not in calls
    assert calls.index("systemctl <show> <acx-gpu-reap.service>") < start_timer_enable


def test_rendered_remote_body_avoids_nonportable_shell_constructs(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health", dry_run=False,
    )
    body = (tmp_path / "remote-body.sh").read_text(encoding="utf-8")
    for pattern in (
        r"\bmv\s+-\w*T", r"\breadlink\s+-f\b", r"\btac\b",
        r"\b(?:mapfile|readarray)\b", r"\$\{[^}]*,,[^}]*\}",
        r"\[\s+(?:-\w\s+)?\$",  # unquoted first test operand
        r"(?:!=|=)\s+\$[^\n]*\]",  # unquoted comparison operand
    ):
        assert not re.search(pattern, body), f"nonportable rendered shell: {pattern}"
    assert result.returncode == 0, result.stdout + result.stderr


def test_fake_ssh_avoids_locale_sensitive_bulk_shell_rewrites(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health", dry_run=False,
    )
    transport = (tmp_path / "bin" / "ssh").read_text(encoding="utf-8")
    # Bash 3.2 in a UTF-8 locale takes tens of seconds per substitution on
    # the rendered body; even a successful Linux run must reject that path.
    assert "${remote_body//" not in transport
    assert result.returncode == 0, result.stdout + result.stderr


def test_release_upgrade_replaces_symlinks_and_preserves_old_directories(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    release_root = tmp_path / "host" / "opt-acx-gpu"
    current = release_root / "current"
    assert current.is_symlink()
    assert current.resolve().parent == release_root / "releases"
    assert (current / "systemd" / "acx-gpu-reap.service").is_file()
    assert (release_root / "previous").resolve() == release_root / "old release"
    assert list((release_root / "older release").iterdir()) == []
    assert list((release_root / "old release").iterdir()) == [release_root / "old release" / "systemd"]
    _assert_rendered_activation_contract(result, calls)


@pytest.mark.parametrize("interval", ["not-a-duration", "0s", "infinity", "", "2min\nOnUnitActiveSec=", "999999999999999999999d"])
def test_invalid_reap_interval_fails_before_transport_or_unit_writes(tmp_path: Path, interval: str) -> None:
    result, calls = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, reap_interval=interval,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "REAP_INTERVAL" in result.stderr
    assert calls == ""
    assert list((tmp_path / "effective-systemd").iterdir()) == []


def test_partial_existing_snapshot_is_never_published_as_previous(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True, snapshot_kind="partial",
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "incomplete rollback snapshot" in result.stderr
    release_root = tmp_path / "host/opt-acx-gpu"
    assert (release_root / "previous").resolve().name == "older release"
    assert (release_root / "current").resolve().name == "old release"


@pytest.mark.parametrize("snapshot_kind", ["complete", "missing"])
@pytest.mark.parametrize("artifact", [
    "gpu-lifecycle.env", "acx-gpu.conf", "acx-gpu-start.service",
    "acx-gpu-start.timer", "acx-gpu-reap.service", "acx-gpu-reap.timer",
])
def test_empty_rollback_artifact_must_not_replace_previous(
    tmp_path: Path, snapshot_kind: str, artifact: str,
) -> None:
    result, calls = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True, snapshot_kind=snapshot_kind,
        empty_rollback_artifact=artifact,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "incomplete rollback snapshot" in result.stderr
    assert artifact in result.stderr
    release_root = tmp_path / "host/opt-acx-gpu"
    assert (release_root / "previous").resolve().name == "older release"
    assert (release_root / "current").resolve().name == "old release"
    assert "systemctl <enable> <--now> <acx-gpu-start.timer>" not in calls
    if snapshot_kind == "missing":
        assert not (release_root / "old release/systemd").exists()
        assert list((release_root / "old release").glob(".systemd.*")) == []
    else:
        assert (release_root / "old release/systemd" / artifact).read_bytes() == b""


def test_snapshot_copy_failure_retry_publishes_only_complete_generation(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True, snapshot_kind="missing", snapshot_copy_failure=True,
    )
    assert result.returncode != 0
    assert "injected snapshot copy failure" in result.stderr
    release_root = tmp_path / "host/opt-acx-gpu"
    assert (release_root / "previous").resolve().name == "older release"
    assert not (release_root / "old release/systemd").exists()

    result, _ = _run_lifecycle(
        tmp_path, enabled=True, ready_url="http://gpu.test:8000/health",
        dry_run=False, previous_release=True, snapshot_kind="missing",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    previous = release_root / "previous"
    assert previous.resolve().name == "old release"
    assert {path.name for path in (previous / "systemd").iterdir()} == {
        "gpu-lifecycle.env", "acx-gpu.conf", "acx-gpu-start.service",
        "acx-gpu-start.timer", "acx-gpu-reap.service", "acx-gpu-reap.timer",
    }


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
    switch = transaction.index("previous_release=\\$(python3 -c")
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

    assert "previous_release=\\$(python3 -c" in source
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
    # Initial LoadState queries prove absent units on a fresh host. Effective
    # artifact verification must not run after the synchronous reaper fails.
    assert "<--property=FragmentPath>" not in calls
    assert "<--property=DropInPaths>" not in calls
    assert "<--property=ExecStart>" not in calls
