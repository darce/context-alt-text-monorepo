"""Regression tests for the GPU lifecycle remote installer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _recorded_call_count(path: Path) -> int:
    return sum(
        line.startswith(("ssh ", "scp ", "--foreground "))
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _run_installer(tmp_path: Path, *arguments: str, scp_exit: int = 0) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    transport_log = tmp_path / "transport.log"
    timeout_log = tmp_path / "timeout.log"
    live_marker = tmp_path / "live-package"
    live_marker.write_text("previous release\n", encoding="utf-8")

    _write_executable(
        fake_bin / "timeout",
        """#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >>"$FAKE_TIMEOUT_LOG"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --foreground|--signal=*|--kill-after=*) shift ;;
        *s) shift; break ;;
        *) break ;;
    esac
done
exec "$@"
""",
    )
    _write_executable(
        fake_bin / "ssh",
        """#!/usr/bin/env bash
set -eu
printf 'ssh %s\\n' "$*" >>"$FAKE_TRANSPORT_LOG"
if [[ "$*" == *'rm -rf /opt/acx-gpu/infra/oci/gpu_lifecycle'* ]]; then
    rm -f "$FAKE_LIVE_MARKER"
fi
""",
    )
    _write_executable(
        fake_bin / "scp",
        """#!/usr/bin/env bash
set -eu
printf 'scp %s\\n' "$*" >>"$FAKE_TRANSPORT_LOG"
exit "$FAKE_SCP_EXIT"
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "GPU_INSTANCE_ID": "ocid1.instance.test",
            "ACX_GPU_DEPLOYMENTS_FILE": str(DEPLOYMENTS),
            "FAKE_LIVE_MARKER": str(live_marker),
            "FAKE_SCP_EXIT": str(scp_exit),
            "FAKE_TIMEOUT_LOG": str(timeout_log),
            "FAKE_TRANSPORT_LOG": str(transport_log),
        }
    )
    result = subprocess.run(
        [str(INSTALLER), "--host", "ubuntu@test.invalid", *arguments],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    result.live_marker = live_marker  # type: ignore[attr-defined]
    result.timeout_log = timeout_log  # type: ignore[attr-defined]
    result.transport_log = transport_log  # type: ignore[attr-defined]
    return result


def test_mid_sequence_scp_failure_leaves_previous_package_serving(tmp_path: Path) -> None:
    result = _run_installer(
        tmp_path,
        "--ready-url",
        "http://127.0.0.1:8000/health/ready",
        scp_exit=77,
    )

    assert result.returncode != 0
    assert result.live_marker.read_text(encoding="utf-8") == "previous release\n"  # type: ignore[attr-defined]
    transport_calls = _recorded_call_count(result.transport_log)  # type: ignore[attr-defined]
    timeout_calls = _recorded_call_count(result.timeout_log)  # type: ignore[attr-defined]
    assert transport_calls, "the fake transport was never invoked"
    assert timeout_calls == transport_calls, (
        "every attempted ssh/scp leg must run beneath its own wall-clock timeout"
    )


def test_readiness_url_is_mandatory_at_install_time(tmp_path: Path) -> None:
    result = _run_installer(tmp_path, "--dry-run")

    assert result.returncode == 2
    assert "--ready-url is required" in result.stderr


def test_idle_seconds_must_be_positive(tmp_path: Path) -> None:
    result = _run_installer(
        tmp_path,
        "--ready-url",
        "http://127.0.0.1:8000/health/ready",
        "--idle-seconds",
        "-1",
        "--dry-run",
    )

    assert result.returncode == 2
    assert "--idle-seconds must be > 0" in result.stderr


def test_generated_units_include_readiness_and_runtime_deadlines(tmp_path: Path) -> None:
    ready_url = "http://127.0.0.1:8000/health/ready"
    result = _run_installer(tmp_path, "--ready-url", ready_url)

    assert result.returncode == 0, result.stdout + result.stderr
    remote_payload = result.transport_log.read_text(encoding="utf-8")  # type: ignore[attr-defined]
    assert f"--ready-url {ready_url}" in remote_payload
    assert remote_payload.count("TimeoutStartSec=") == 2
    assert remote_payload.count("RuntimeMaxSec=") == 2
    assert "renameat2" in remote_payload, "the live package switch must be one atomic exchange"
    timeout_calls = _recorded_call_count(result.timeout_log)  # type: ignore[attr-defined]
    transport_calls = _recorded_call_count(result.transport_log)  # type: ignore[attr-defined]
    assert timeout_calls == transport_calls == 4
