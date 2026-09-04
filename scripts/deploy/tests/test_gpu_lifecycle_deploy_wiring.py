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
    instance_id: str = "ocid1.instance.oc1.test",
    drop_in_paths: str = "",
    mismatched_unit: str | None = None,
    reap_exec_start: str = (
        "/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap "
        "--max-lease-seconds ${MAX_LEASE_SECONDS}"
    ),
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
    if mismatched_unit is not None:
        (effective_systemd / mismatched_unit).write_text("stale effective unit\n", encoding="utf-8")
    lifecycle_env = tmp_path / "gpu-lifecycle.env"
    lifecycle_env.write_text("MAX_LEASE_SECONDS=3600\n", encoding="utf-8")
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'ssh' >>"$FAKE_TRANSPORT_LOG"
printf ' <%s>' "$@" >>"$FAKE_TRANSPORT_LOG"
printf '\n' >>"$FAKE_TRANSPORT_LOG"
case "$*" in
  *"sudo systemctl start acx-gpu-reap.service"*)
    systemctl start acx-gpu-reap.service
    "$FAKE_INSTALLER" --verify-systemd-only || {
      status=$?
      systemctl disable --now acx-gpu-start.timer
      exit "$status"
    }
    ;;
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
if [ "$1" = show ]; then
  case "$*" in
    *"--property=FragmentPath"*) printf '%s/%s\n' "$ACX_EFFECTIVE_SYSTEMD_DIR" "$2" ;;
    *"--property=DropInPaths"*) printf '%s\n' "${FAKE_DROP_IN_PATHS:-}" ;;
    *"--property=ExecStart"*)
      printf '%s\n' "$FAKE_REAP_EXEC_START"
      ;;
  esac
  exit 0
fi
if [ "$1" = is-active ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  exit "${FAKE_VERIFY_RC:-0}"
fi
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
            "FAKE_DROP_IN_PATHS": drop_in_paths,
            "FAKE_REAP_EXEC_START": reap_exec_start,
            "FAKE_INSTALLER": str(INSTALLER),
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


def test_flag_on_rejects_non_instance_ocid_before_transport(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        instance_id="ocid1.volume.oc1.test",
    )

    assert result.returncode == 2
    assert "ACX_GPU_INSTANCE_ID" in result.stderr
    assert "ocid1.instance.oc1." in result.stderr
    assert calls == ""


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
    assert "systemctl is-enabled" in calls
    assert "systemctl is-active" in calls
    assert "acx-gpu-start.timer is not active" in result.stderr
    for ssh_call in (line for line in calls.splitlines() if line.startswith("ssh")):
        assert "<-l> <ci-user> <--> <backend.test>" in ssh_call


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
if [ "$1" = is-active ] && [ "${3:-}" = acx-gpu-start.timer ]; then
  exit 3
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

    result = subprocess.run(
        [str(INSTALLER), "--verify-systemd-only"],
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
    reap_proof = calls.index("sudo systemctl start acx-gpu-reap.service")
    start_timer_enable = calls.index("sudo systemctl enable --now acx-gpu-start.timer")
    assert reap_proof < start_timer_enable
    assert "systemctl start acx-gpu-start" not in calls

    assert calls.index("start_timer_armed=1") < calls.index(
        "sudo systemctl enable --now acx-gpu-start.timer"
    )
    assert calls.index("sudo systemctl enable --now acx-gpu-start.timer") < calls.rindex(
        "verify_gpu_lifecycle_timers"
    )
    assert calls.rindex("verify_gpu_lifecycle_timers") < calls.rindex("trap - EXIT")


def test_every_remote_shell_enables_pipefail() -> None:
    source = INSTALLER.read_text(encoding="utf-8")

    remote_shells = source.count('ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail')
    assert remote_shells == 3
    assert 'ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -eu\n' not in source


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
