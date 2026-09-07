"""Shell-level regression tests for the GPU lifecycle installer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.deploy.tests.test_gpu_lifecycle_contract_ownership import _api_runtime_ids
from scripts.deploy.tests.test_gpu_lifecycle_deploy_wiring import _run_lifecycle

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"
CONTRACT = REPO_ROOT / "docs/workbay/contracts/gpu-lifecycle.md"
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


@pytest.mark.parametrize("name", ["START_INTERVAL", "REAP_INTERVAL"])
@pytest.mark.parametrize("interval", ["1s", "30s", "2min", "1h", "1d"])
def test_installer_accepts_supported_monotonic_intervals(name: str, interval: str) -> None:
    result = _run_installer(environment={name: interval, "READY_URL": "http://gpu.test/health"})
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("interval", ["0s", "-1s", "1.5s", "1h 2min", "daily", "1", "1ms", " 1s", "1s\n"])
def test_installer_rejects_unsupported_start_intervals(interval: str) -> None:
    result = _run_installer(environment={"START_INTERVAL": interval, "READY_URL": "http://gpu.test/health"})
    assert result.returncode != 0
    assert "START_INTERVAL" in result.stderr


def test_installer_requires_readiness_url() -> None:
    result = _run_installer("--idle-seconds", "300")

    assert result.returncode != 0
    assert "READY_URL" in result.stderr


def test_start_unit_always_executes_a_readiness_probe() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    start_unit = re.search(
        r"sudo tee [^\n]*/acx-gpu-start\.service.*?<<UNIT\n(.*?)\nUNIT",
        script, flags=re.DOTALL,
    ).group(1)

    assert "--ready-url" in start_unit
    assert "${READY_URL}" in start_unit


def test_lifecycle_units_pass_the_operator_intent_directory() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    services = re.findall(
        r"sudo tee [^\n]*/acx-gpu-(?:start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )

    assert len(services) == 2
    for service in services:
        assert "--intent-dir /run/acx-write" in service


def test_intent_allowlist_matches_contract_environments() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    contract = CONTRACT.read_text(encoding="utf-8")

    allowlist = re.search(r'^GPU_INTENT_ENVIRONMENTS="([^"]+)"$', script, flags=re.MULTILINE)
    contract_environments = re.search(
        r"`ACX_ENV`\s+is\s+`([^`]+)`,\s*`([^`]+)`,\s+or\s+`([^`]+)`",
        contract,
    )

    assert allowlist is not None
    assert contract_environments is not None
    assert allowlist.group(1).split() == list(contract_environments.groups())


def test_intent_path_unit_watches_only_contract_environments_and_starts_gpu() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    path_unit = re.search(
        r"sudo tee [^\n]*/acx-gpu-intent\.path.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )

    assert path_unit is not None
    content = path_unit.group(1)
    assert "${INTENT_PATH_ENTRIES}" in content
    append_deployment = script[script.index("append_deployment()") : script.index("load_deployments()")]
    assert "GPU_INTENT_ENVIRONMENTS" in append_deployment
    assert "PathChanged=/run/acx-write/${environment}/gpu-intent.json" in append_deployment
    registered_environments = set(DEPLOYMENTS.read_text(encoding="utf-8").split())
    assert {"dev", "staging", "prod"} <= registered_environments
    assert "dev-fir" in registered_environments
    assert "Unit=acx-gpu-start.service" in content
    assert "acx-gpu-intent.path" in script
    assert "systemctl enable --now acx-gpu-intent.path" in script


def test_intent_path_is_fenced_before_release_mutation_and_on_failure() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    transaction = script[script.index('run_with_deadline "systemd unit installation"') :]

    assert "sudo systemctl disable --now acx-gpu-intent.path" in script
    assert transaction.index("fence_gpu_intent_path") < transaction.index(
        "previous_release=\\$(python3 -c"
    )
    assert transaction.index("fence_gpu_intent_path") < transaction.index("activate_gpu_lifecycle_timers \\")
    cleanup = script[script.index("cleanup_gpu_lifecycle_transaction()") : script.index("# Hermetic verification")]
    assert cleanup.index("fence_gpu_intent_path") < cleanup.index("fence_gpu_lifecycle_start")
    assert script.index("sudo systemctl enable --now acx-gpu-intent.path") > script.index(
        "verify_gpu_lifecycle_start_timer"
    )


def test_installer_purges_cloud_init_idle_reaper_units() -> None:
    script = INSTALLER.read_text(encoding="utf-8")

    assert "acx-gpu-idle-reaper.service" in script
    assert "acx-gpu-idle-reaper.timer" in script
    assert "systemctl disable --now" in script
    assert "systemctl daemon-reload" in script
    assert 'rm -f "/etc/systemd/system/$unit"' in script


def test_oneshot_units_have_systemd_execution_deadlines() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    services = re.findall(
        r"sudo tee [^\n]*/acx-gpu-(?:start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )

    assert len(services) == 2
    for service in services:
        assert re.search(r"^TimeoutStartSec=\d+s$", service, flags=re.MULTILINE)
        assert re.search(r"^RuntimeMaxSec=\d+s$", service, flags=re.MULTILINE)


def test_timers_delay_their_first_trigger_relative_to_activation_not_boot() -> None:
    """A boot-relative first trigger is already elapsed on a redeploy.

    Both timers are enabled with `systemctl enable --now` against a host that has been
    up for hours. systemd.timer(5): an OnBootSec deadline in the past fires the unit
    immediately at activation, so the settling window would be skipped on every
    redeploy and the start poll could power the GPU on before the load snapshot the
    poll reads has been written. OnActiveSec is measured from activation instead, which
    is the same delay at boot and the intended delay on a running host.
    """
    script = INSTALLER.read_text(encoding="utf-8")
    timers = dict(
        re.findall(
            r"sudo tee [^\n]*/acx-gpu-(start|reap)\.timer.*?<<UNIT\n(.*?)\nUNIT",
            script,
            flags=re.DOTALL,
        )
    )

    assert set(timers) == {"start", "reap"}
    for name, timer in timers.items():
        assert "OnBootSec=" not in timer, f"acx-gpu-{name}.timer would fire immediately on a redeploy"
        assert re.search(r"^OnActiveSec=\d+min$", timer, flags=re.MULTILINE), (
            f"acx-gpu-{name}.timer has no activation-relative first trigger"
        )
        assert re.search(r"^OnUnitActiveSec=", timer, flags=re.MULTILINE)


def test_oneshot_units_share_persistent_boot_fenced_lifecycle_state() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    services = re.findall(
        r"sudo tee [^\n]*/acx-gpu-(?:start|reap)\.service.*?<<UNIT\n(.*?)\nUNIT",
        script,
        flags=re.DOTALL,
    )

    assert len(services) == 2
    for service in services:
        assert "StateDirectory=acx-gpu" in service
        assert "--running-since-path /var/lib/acx-gpu/running-since.json" in service
        assert "/usr/bin/flock --wait 120 /var/lib/acx-gpu/lifecycle.lock" in service
        assert "RuntimeDirectory=acx-gpu" not in service


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
    assert "os.replace(sys.argv[1], sys.argv[2])" in script
    assert "WorkingDirectory=/opt/acx-gpu/current" in script
    assert "rm -rf /opt/acx-gpu/infra/oci/gpu_lifecycle" not in script

    stage_position = script.index('remote_stage="/opt/acx-gpu/releases/.staging-')
    copy_position = script.index('scp -q "${SSH_OPTIONS[@]}"')
    validate_position = script.index("python3 -c 'import infra.oci.gpu_lifecycle.reaper'")
    switch_position = script.index("' '/opt/acx-gpu/.current-${release_id}' /opt/acx-gpu/current")
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


def test_installer_provisions_every_supplementary_group_it_references(tmp_path: Path) -> None:
    """The remote installer payload must provision the NSS group before activation.

    A fresh host starts without the image-pinned runtime GID. Execute the rendered payload through
    the shared remote shim so this test observes the real ``getent``/``groupadd``
    sequence rather than proving that those words occur in the installer source.
    """
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://10.0.1.36:8000/health",
        dry_run=False,
        group_present=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    groupadd = "groupadd <-r> <-g> <10001> <acxapi>"
    getent = "getent <group> <10001>"
    assert groupadd in calls
    assert calls.count(getent) >= 2, "the payload must verify the GID before and after groupadd"
    assert calls.index(getent) < calls.index(groupadd) < calls.rindex(getent)
    assert calls.rindex(getent) < calls.index("systemctl <start> <acx-gpu-reap.service>")
    group_db = (tmp_path / "fake-etc-group").read_text(encoding="utf-8")
    _, image_gid = _api_runtime_ids()
    groups_by_name = {
        fields[0]: fields[2]
        for line in group_db.splitlines()
        if (fields := line.split(":")) and len(fields) >= 3
    }
    assert image_gid in groups_by_name.values(), (
        "the executed installer must leave the image-pinned GID resolvable in the fake NSS database"
    )
    for unit in ("acx-gpu-start.service", "acx-gpu-reap.service"):
        rendered = (tmp_path / "effective-systemd" / unit).read_text(encoding="utf-8")
        match = re.search(r"^SupplementaryGroups=(?P<group>\S+)$", rendered, flags=re.MULTILINE)
        assert match is not None, f"{unit} must name its supplementary group"
        group_name = match["group"]
        assert group_name in groups_by_name, (
            f"{unit} names supplementary group {group_name!r}, but the fake NSS database "
            f"does not contain that group: {group_db!r}"
        )
        assert groups_by_name[group_name] == image_gid, (
            f"{unit} names supplementary group {group_name!r}, which resolves to "
            f"GID {groups_by_name[group_name]}, not image-pinned GID {image_gid}"
        )
