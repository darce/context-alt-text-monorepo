"""Shell-level regression tests for the GPU lifecycle installer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"
FAKE_GPU_INSTANCE_ID = (
    "ocid1.instance.oc1.phx."
    "anyhqljtestfakegpu000000000000000000000000000000000000000000"
)


def _run_installer(*arguments: str, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    command_environment = os.environ.copy()
    command_environment.update(
        {
            "ACX_GPU_DEPLOYMENTS_FILE": str(DEPLOYMENTS),
            "GPU_INSTANCE_ID": FAKE_GPU_INSTANCE_ID,
        }
    )
    if environment:
        command_environment.update(environment)
    return subprocess.run(
        [str(INSTALLER), "--host", "test.invalid", *arguments, "--dry-run"],
        cwd=REPO_ROOT,
        env=command_environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("idle_seconds", ["-1", "0", "abc", "", " 1", "1 ", "+1"])
def test_installer_rejects_non_positive_idle_seconds(idle_seconds: str) -> None:
    result = _run_installer(
        environment={
            "IDLE_SECONDS": idle_seconds,
            "READY_URL": "http://10.0.1.2:8000/health",
        }
    )

    assert result.returncode != 0
    assert "IDLE_SECONDS" in result.stderr


def test_installer_accepts_positive_idle_seconds() -> None:
    result = _run_installer(
        environment={
            "IDLE_SECONDS": "300",
            "READY_URL": "http://10.0.1.2:8000/health",
        }
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_installer_requires_readiness_url() -> None:
    result = _run_installer("--idle-seconds", "300")

    assert result.returncode != 0
    assert "READY_URL" in result.stderr


def test_start_unit_always_executes_a_readiness_probe() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    start_unit = script.split("sudo tee /etc/systemd/system/acx-gpu-start.service", 1)[1].split("\nUNIT", 1)[0]

    assert "--ready-url" in start_unit
    assert "${READY_URL}" in start_unit


def test_oneshot_units_have_systemd_execution_deadlines() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    services = re.findall(
        r"tee /etc/systemd/system/acx-gpu-(?:start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )

    assert len(services) == 2
    for service in services:
        assert re.search(r"^TimeoutStartSec=\d+s$", service, flags=re.MULTILINE)
        assert re.search(r"^RuntimeMaxSec=\d+s$", service, flags=re.MULTILINE)


def test_transport_is_bounded_and_release_switch_is_atomic() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    for option in (
        "BatchMode=yes",
        "ConnectTimeout=",
        "ServerAliveInterval=",
        "ServerAliveCountMax=",
    ):
        assert option in script
    assert "run_with_deadline" in script
    assert "/opt/acx-gpu/releases/" in script
    assert "python3 -c 'import infra.oci.gpu_lifecycle.reaper'" in script
    assert "mv -Tf" in script
    assert "WorkingDirectory=/opt/acx-gpu/current" in script
    assert "rm -rf /opt/acx-gpu/infra/oci/gpu_lifecycle" not in script

    stage_position = script.index('remote_stage="/opt/acx-gpu/releases/.staging-')
    copy_position = script.index('scp -q "${SSH_OPTIONS[@]}"')
    validate_position = script.index("python3 -c 'import infra.oci.gpu_lifecycle.reaper'")
    switch_position = script.index("sudo mv -Tf '/opt/acx-gpu/.current-${release_id}' /opt/acx-gpu/current")
    assert stage_position < copy_position < validate_position < switch_position


@pytest.mark.parametrize("idle_seconds", ["-1", "0", "abc", "", " 1", "1 ", "+1"])
def test_idle_seconds_cli_type_rejects_non_positive_values(idle_seconds: str) -> None:
    command = [
        sys.executable,
        "-c",
        (
            "from infra.oci.gpu_lifecycle.reaper import _build_parser; "
            "_build_parser().parse_args(['--instance-id', 'ocid1.test', "
            f"'--idle-seconds', {idle_seconds!r}])"
        ),
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "positive integer" in result.stderr


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def test_mid_sequence_copy_failure_never_switches_the_live_release(tmp_path: Path) -> None:
    """A failed module copy must leave `current` pointing at the previous release."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    transport_log = tmp_path / "transport.log"

    _write_executable(
        fake_bin / "ssh",
        '#!/usr/bin/env bash\nset -eu\nprintf \'ssh %s\\n\' "$*" >>"$FAKE_TRANSPORT_LOG"\n',
    )
    _write_executable(
        fake_bin / "scp",
        '#!/usr/bin/env bash\nset -eu\nprintf \'scp %s\\n\' "$*" >>"$FAKE_TRANSPORT_LOG"\nexit 77\n',
    )

    command_environment = os.environ.copy()
    command_environment.update(
        {
            "ACX_GPU_DEPLOYMENTS_FILE": str(DEPLOYMENTS),
            "GPU_INSTANCE_ID": FAKE_GPU_INSTANCE_ID,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_TRANSPORT_LOG": str(transport_log),
        }
    )
    result = subprocess.run(
        [
            str(INSTALLER),
            "--host",
            "test.invalid",
            "--ready-url",
            "http://127.0.0.1:8000/health/ready",
        ],
        cwd=REPO_ROOT,
        env=command_environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    calls = transport_log.read_text(encoding="utf-8") if transport_log.exists() else ""
    assert "scp " in calls, "the copy leg was never attempted"
    assert "/opt/acx-gpu/current" not in calls, (
        "the live release was switched despite a failed module copy"
    )
