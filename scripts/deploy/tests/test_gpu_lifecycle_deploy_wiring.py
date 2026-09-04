"""Deploy-pipeline wiring for the GPU lifecycle timers (no live host)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY = REPO_ROOT / "scripts/deploy/recognition-service.sh"


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
) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    transport_log = tmp_path / "transport.log"
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -eu
printf 'ssh' >>"$FAKE_TRANSPORT_LOG"
printf ' <%s>' "$@" >>"$FAKE_TRANSPORT_LOG"
printf '\n' >>"$FAKE_TRANSPORT_LOG"
case "$*" in
  *"systemctl is-enabled"*)
    if [ "${FAKE_VERIFY_RC:-0}" -ne 0 ]; then
      echo "error: acx-gpu-start.timer is not active" >&2
      exit "$FAKE_VERIFY_RC"
    fi
    ;;
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
            "GPU_INSTANCE_ID": "ocid1.instance.test",
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_TRANSPORT_LOG": str(transport_log),
            "FAKE_VERIFY_RC": str(verify_rc),
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

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ""
    assert "disabled" in (result.stdout + result.stderr).lower()


def test_flag_on_requires_explicit_ready_url(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(tmp_path, enabled=True, ready_url=None)

    assert result.returncode != 0
    assert "ACX_GPU_READY_URL is required when ACX_DEPLOY_GPU_LIFECYCLE=1" in result.stderr
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
