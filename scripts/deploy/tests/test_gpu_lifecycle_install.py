"""Shell-level regression tests for the GPU lifecycle installer."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _write_executable

from scripts.deploy.tests.test_gpu_lifecycle_contract_ownership import _api_runtime_ids
from scripts.deploy.tests.test_gpu_lifecycle_deploy_wiring import _run_lifecycle

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALLER = REPO_ROOT / "scripts/deploy/gpu-lifecycle-install.sh"
DEPLOYMENTS = REPO_ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"
CONTRACT = REPO_ROOT / "docs/workbay/contracts/gpu-lifecycle.md"
FAKE_GPU_INSTANCE_ID = "ocid1.instance.oc1.phx.anyhqljtestfakegpu000000000000000000000000000000000000000000"


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


@pytest.fixture(scope="module")
def successful_lifecycle_install(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    install_root = tmp_path_factory.mktemp("gpu-lifecycle-install")
    result, calls = _run_lifecycle(
        install_root,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        full_remote_install=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return install_root, calls


def _parse_systemd_unit(path: Path) -> dict[tuple[str, str], list[str]]:
    """Parse rendered directives while retaining repeated keys such as PathChanged."""
    directives: dict[tuple[str, str], list[str]] = {}
    section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        key, separator, value = line.partition("=")
        if separator:
            directives.setdefault((section, key), []).append(value)
    return directives


def _rendered_unit(install_root: Path, name: str) -> dict[tuple[str, str], list[str]]:
    return _parse_systemd_unit(install_root / "effective-systemd" / name)


def _rendered_execstart(unit: dict[tuple[str, str], list[str]]) -> list[str]:
    return shlex.split(unit[("Service", "ExecStart")][0])


def _contract_intent_environments() -> list[str]:
    contract = CONTRACT.read_text(encoding="utf-8")
    match = re.search(
        r"`ACX_ENV`\s+is\s+`([^`]+)`,\s*`([^`]+)`,\s+or\s+`([^`]+)",
        contract,
    )
    assert match is not None
    return list(match.groups())


def _mapped_intent_path(install_root: Path, environment: str) -> str:
    return str(install_root / "host" / "run-acx-write" / environment / "gpu-intent.json")


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


def _assert_service_readiness_url(install_root: Path, service_name: str) -> None:
    unit = _rendered_unit(install_root, service_name)
    arguments = _rendered_execstart(unit)
    assert "--ready-url" in arguments
    assert arguments[arguments.index("--ready-url") + 1] == "${READY_URL}"

    environment_files = unit[("Service", "EnvironmentFile")]
    assert len(environment_files) == 1
    environment = dict(
        line.split("=", 1)
        for line in Path(environment_files[0]).read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert environment["READY_URL"] == "http://gpu.test/health/ready"


def test_start_unit_always_executes_a_readiness_probe(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    _assert_service_readiness_url(successful_lifecycle_install[0], "acx-gpu-start.service")


def test_reap_unit_always_executes_a_readiness_probe(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    _assert_service_readiness_url(successful_lifecycle_install[0], "acx-gpu-reap.service")


def test_lifecycle_units_pass_the_operator_intent_directory(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    install_root, _ = successful_lifecycle_install
    expected_intent_directory = str(install_root / "host" / "run-acx-write")
    for service_name in ("acx-gpu-start.service", "acx-gpu-reap.service"):
        arguments = _rendered_execstart(_rendered_unit(install_root, service_name))
        assert arguments[arguments.index("--intent-dir") + 1] == expected_intent_directory


def test_intent_allowlist_matches_contract_environments(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    install_root, _ = successful_lifecycle_install
    expected_paths = [
        _mapped_intent_path(install_root, environment)
        for environment in _contract_intent_environments()
    ]
    watcher = _rendered_unit(install_root, "acx-gpu-intent.path")
    assert watcher[("Path", "PathChanged")] == expected_paths


def test_intent_path_unit_watches_only_contract_environments_and_starts_gpu(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    install_root, calls = successful_lifecycle_install
    watcher = _rendered_unit(install_root, "acx-gpu-intent.path")
    assert watcher[("Path", "Unit")] == ["acx-gpu-start.service"]
    assert "systemctl <enable> <--now> <acx-gpu-intent.path>" in calls


def test_registry_addition_gets_tmpfiles_directory_without_intent_trigger(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        extra_registry_environment=("qa",),
        full_remote_install=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    tmpfiles = (tmp_path / "host" / "etc-tmpfiles" / "acx-gpu.conf").read_text(encoding="utf-8")
    environment_root = str(tmp_path / "host" / "run-acx-write") + "/"
    tmpfile_paths = [
        line.split()[1]
        for line in tmpfiles.splitlines()
        if line.startswith("d ") and line.split()[1].startswith(environment_root)
    ]
    assert tmpfile_paths == [
        str(tmp_path / "host" / "run-acx-write" / environment)
        for environment in (*DEPLOYMENTS.read_text(encoding="utf-8").split(), "qa")
    ]
    watcher = _parse_systemd_unit(tmp_path / "effective-systemd" / "acx-gpu-intent.path")
    assert watcher[("Path", "PathChanged")] == [
        _mapped_intent_path(tmp_path, environment) for environment in _contract_intent_environments()
    ]


def test_intent_path_is_fenced_before_release_mutation_and_on_failure(tmp_path: Path) -> None:
    result, _ = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        previous_release=True,
        seed_intent_path_active=True,
        full_remote_install=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    first_fence = events.index("systemctl-disable-intent-path")
    current_switch = next(
        index for index, event in enumerate(events)
        if event.startswith("atomic-replace ") and event.endswith("/current>")
    )
    assert first_fence < current_switch
    assert "intent-path-inactive-at-current-switch" in events
    assert (tmp_path / "intent-path.active").exists()
    assert (tmp_path / "intent-path.enabled").exists()
    last_start_verification = max(
        index for index, event in enumerate(events) if event == "systemctl-verify-start-timer"
    )
    assert events.index("systemctl-enable-intent-path") > last_start_verification

    failure_root = tmp_path / "failure"
    failure_root.mkdir()
    failed, _ = _run_lifecycle(
        failure_root,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        previous_release=True,
        seed_intent_path_active=True,
        external_failure="unit-write",
        full_remote_install=True,
    )
    assert failed.returncode != 0, failed.stdout + failed.stderr
    assert "injected-unit-write-failure" in (failure_root / "events.log").read_text(encoding="utf-8")
    failure_events = (failure_root / "events.log").read_text(encoding="utf-8").splitlines()
    intent_fences = [i for i, event in enumerate(failure_events) if event == "systemctl-disable-intent-path"]
    start_fences = [i for i, event in enumerate(failure_events) if event == "systemctl-disable-start-timer"]
    assert len(intent_fences) >= 2, "failure cleanup must fence intent again"
    assert intent_fences[-1] < start_fences[-1], "cleanup must fence intent before lifecycle start"
    assert not (failure_root / "intent-path.active").exists()
    assert not (failure_root / "intent-path.enabled").exists()


def test_installer_purges_cloud_init_idle_reaper_units(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        seed_stale_reaper_units=True,
        full_remote_install=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    effective_systemd = tmp_path / "effective-systemd"
    removal_events = []
    for unit in ("acx-gpu-idle-reaper.timer", "acx-gpu-idle-reaper.service"):
        assert f"systemctl <disable> <--now> <{unit}>" in calls
        assert not (effective_systemd / unit).exists()
        assert f"systemctl-disable-stale <{unit}>" in events
        removal = next(index for index, event in enumerate(events) if event.startswith("sudo-rm") and unit in event)
        removal_events.append(removal)
    reload = next(index for index, event in enumerate(events) if event == "systemctl-daemon-reload")
    unit_write = next(
        index for index, event in enumerate(events)
        if event.startswith("sudo-tee") and "acx-gpu-start.service" in event
    )
    assert max(removal_events) < reload < unit_write


def test_oneshot_units_have_systemd_execution_deadlines(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    install_root, _ = successful_lifecycle_install
    for service_name in ("acx-gpu-start.service", "acx-gpu-reap.service"):
        unit = _rendered_unit(install_root, service_name)
        for key in ("TimeoutStartSec", "RuntimeMaxSec"):
            value = unit[("Service", key)][0]
            assert re.fullmatch(r"[1-9][0-9]*s", value), f"{service_name} has no positive {key}"


def test_timers_delay_their_first_trigger_relative_to_activation_not_boot(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    """A boot-relative first trigger is already elapsed on a redeploy.

    Both timers are enabled with `systemctl enable --now` against a host that has been
    up for hours. systemd.timer(5): an OnBootSec deadline in the past fires the unit
    immediately at activation, so the settling window would be skipped on every
    redeploy and the start poll could power the GPU on before the load snapshot the
    poll reads has been written. OnActiveSec is measured from activation instead, which
    is the same delay at boot and the intended delay on a running host.
    """
    install_root = successful_lifecycle_install[0]
    for name in ("start", "reap"):
        timer = _rendered_unit(install_root, f"acx-gpu-{name}.timer")
        assert ("Timer", "OnBootSec") not in timer
        assert re.fullmatch(r"[1-9][0-9]*min", timer[("Timer", "OnActiveSec")][0])
        assert timer[("Timer", "OnUnitActiveSec")][0]


def test_oneshot_units_share_persistent_boot_fenced_lifecycle_state(
    successful_lifecycle_install: tuple[Path, str]
) -> None:
    install_root = successful_lifecycle_install[0]
    expected_state = str(install_root / "host" / "var-lib-acx-gpu")
    for service_name in ("acx-gpu-start.service", "acx-gpu-reap.service"):
        unit = _rendered_unit(install_root, service_name)
        arguments = _rendered_execstart(unit)
        assert unit[("Service", "StateDirectory")] == ["acx-gpu"]
        assert ("Service", "RuntimeDirectory") not in unit
        assert arguments[arguments.index("--running-since-path") + 1] == f"{expected_state}/running-since.json"
        assert arguments[:3] == ["/usr/bin/flock", "--wait", "120"]
        assert arguments[3] == f"{expected_state}/lifecycle.lock"


def test_transport_is_bounded_and_release_switch_is_atomic(tmp_path: Path) -> None:
    result, calls = _run_lifecycle(
        tmp_path,
        enabled=True,
        ready_url="http://gpu.test/health/ready",
        dry_run=False,
        previous_release=True,
        full_remote_install=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    transport_calls = calls.splitlines()
    ssh_calls = [line for line in transport_calls if line.startswith("ssh")]
    scp_calls = [line for line in transport_calls if line.startswith("scp")]
    assert len(ssh_calls) >= 3 and len(scp_calls) == 2
    for line in (*ssh_calls, *scp_calls):
        arguments = re.findall(r"<([^>]*)>", line)
        assert "BatchMode=yes" in arguments
        for option in ("ConnectTimeout", "ServerAliveInterval", "ServerAliveCountMax"):
            match = next((re.fullmatch(rf"{option}=([1-9][0-9]*)", value) for value in arguments if value.startswith(f"{option}=")), None)
            assert match is not None, f"{line} lacks a positive {option}"

    host = tmp_path / "host"
    current = host / "opt-acx-gpu" / "current"
    assert current.is_symlink()
    release = current.resolve()
    assert release != host / "opt-acx-gpu" / "old release"
    assert (release / "infra" / "oci" / "gpu_lifecycle" / "reaper.py").is_file()
    assert (host / "opt-acx-gpu" / "old release" / "infra" / "oci" / "gpu_lifecycle" / "prior-release-marker").is_file()

    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    copied_reaper = next(i for i, event in enumerate(events) if event.startswith("copy ") and event.endswith("/reaper.py>"))
    imported = next(i for i, event in enumerate(events) if event.startswith("release-import-ok "))
    published_release = next(i for i, event in enumerate(events) if event.startswith("sudo-mv ") and ".staging-" in event)
    assert copied_reaper < imported < published_release

    current_replacements = [
        event for event in events
        if event.startswith("atomic-replace ") and event.endswith("/current>")
    ]
    assert len(current_replacements) == 1
    assert not any(event.startswith("rm ") and event.endswith("/current>") for event in events)
    assert not any(event.startswith("ln ") and event.endswith("/current>") for event in events)
    for service_name in ("acx-gpu-start.service", "acx-gpu-reap.service"):
        unit = _rendered_unit(tmp_path, service_name)
        assert unit[("Service", "WorkingDirectory")] == [str(current)]


@pytest.mark.parametrize("idle_seconds", ["-1", "0", "abc", "", " 1", "1 ", "+1"])
def test_idle_seconds_cli_type_rejects_non_positive_values(tmp_path: Path, idle_seconds: str) -> None:
    oci_invoked = tmp_path / "oci-invoked"
    fake_oci = tmp_path / "oci"
    _write_executable(
        fake_oci,
        f"#!/usr/bin/env bash\nprintf invoked >{shlex.quote(str(oci_invoked))}\nexit 0\n",
    )
    command = [
        sys.executable,
        "-m",
        "infra.oci.gpu_lifecycle",
        "--instance-id",
        "ocid1.test",
        "--idle-seconds",
        idle_seconds,
        "--oci-bin",
        str(fake_oci),
        "--fence-delay-seconds",
        "0",
        "--ready-sleep-seconds",
        "0",
        "--max-wait-seconds",
        "1",
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr.lower()
    assert "positive integer" in result.stderr
    assert not oci_invoked.exists(), "argparse must reject before invoking the OCI command"


def test_idle_seconds_public_cli_help_is_a_valid_parse_control() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "infra.oci.gpu_lifecycle", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "--idle-seconds" in result.stdout


@pytest.mark.parametrize("failure", ["copy", "import", "stall"])
def test_mid_sequence_transport_or_import_failure_preserves_the_live_release(
    tmp_path: Path, failure: str
) -> None:
    if failure == "stall":
        with pytest.raises(AssertionError, match="GPU lifecycle module copy exceeded 1s"):
            _run_lifecycle(
                tmp_path,
                enabled=True,
                ready_url="http://gpu.test/health/ready",
                dry_run=False,
                previous_release=True,
                external_failure=failure,
                remote_timeout=1,
                fixture_timeout=5,
                full_remote_install=True,
            )
    else:
        result, _ = _run_lifecycle(
            tmp_path,
            enabled=True,
            ready_url="http://gpu.test/health/ready",
            dry_run=False,
            previous_release=True,
            external_failure=failure,
            full_remote_install=True,
        )
        assert result.returncode != 0, result.stdout + result.stderr
    host = tmp_path / "host"
    current = host / "opt-acx-gpu" / "current"
    assert current.is_symlink()
    assert current.resolve() == host / "opt-acx-gpu" / "old release"
    assert (current / "infra" / "oci" / "gpu_lifecycle" / "prior-release-marker").is_file()
    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    assert not any(event.startswith("atomic-replace ") and event.endswith("/current>") for event in events)
    if failure == "import":
        assert any(event.startswith("release-import-attempt ") for event in events)
        assert not any(event.startswith("release-import-ok ") for event in events)
    elif failure == "copy":
        assert "injected-copy-failure" in events
    else:
        assert "fake-stalled-scp" in events


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
        fields[0]: fields[2] for line in group_db.splitlines() if (fields := line.split(":")) and len(fields) >= 3
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
