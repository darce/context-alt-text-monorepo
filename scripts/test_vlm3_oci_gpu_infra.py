import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
OCI_ROOT = REPO_ROOT / "infra" / "oci"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gpu_spike_bench as bench  # noqa: E402 - path setup enables script import


def _gpu_instance_block() -> str:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    start = main_tf.index('resource "oci_core_instance" "acx_gpu_burst"')
    rest = main_tf[start:]
    end = rest.find("\nresource ")
    return rest if end < 0 else rest[:end]


def test_gpu_instance_dedicated_tag_matches_bench_gate() -> None:
    gpu_block = _gpu_instance_block()
    key, expected_value = bench.BENCH_DEDICATED_TAG
    tag_match = re.search(rf'"{re.escape(key)}"\s*=\s*"([^"]+)"', gpu_block)

    assert tag_match is not None, f"GPU instance must declare the {key!r} tag"
    assert tag_match.group(1) == expected_value


def test_gpu_instance_ignores_runtime_state_drift_after_reaper_stop() -> None:
    gpu_block = _gpu_instance_block()
    lifecycle = re.search(r"lifecycle\s*\{([^}]*)\}", gpu_block, re.DOTALL)

    assert lifecycle is not None
    assert re.search(r"ignore_changes\s*=\s*\[\s*state\s*\]", lifecycle.group(1))


def test_gpu_instance_uses_configurable_a10_shape_and_dedicated_cloud_init() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    variables_tf = (OCI_ROOT / "variables.tf").read_text()

    assert 'variable "gpu_shape"' in variables_tf
    assert 'default     = "VM.GPU.A10.1"' in variables_tf
    assert 'resource "oci_core_instance" "acx_gpu_burst"' in main_tf
    assert "shape               = var.gpu_shape" in main_tf
    assert 'source_type             = "image"' in main_tf
    assert "source_id               = var.gpu_image_ocid" in main_tf
    assert "boot_volume_size_in_gbs = var.gpu_boot_volume_size_in_gbs" in main_tf
    assert 'display_name        = "acx-gpu-burst"' in main_tf
    assert 'user_data           = base64encode(templatefile("${path.module}/gpu-cloud-init.yaml"' in main_tf
    # First-boot RUNNING so cloud-init finishes; operator stops after bootstrap (S2-05).
    assert 'state = "RUNNING"' in main_tf
    assert "cloud-init" in main_tf.lower() or "gpu-cloud-init" in main_tf


def test_gpu_watchdog_rollout_checks_capacity_and_preserves_existing_boot_volume() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    gpu_block = _gpu_instance_block()

    assert 'resource "oci_core_compute_capacity_report" "acx_gpu_replacement"' in main_tf
    assert "shape_availabilities" in main_tf
    assert "availability_status == \"AVAILABLE\"" in main_tf
    assert "available_count >= 1" in main_tf
    assert "create_before_destroy = true" in gpu_block
    assert "preserve_boot_volume = true" in gpu_block
    assert "precondition" in gpu_block
    assert "metadata.user_data" in main_tf
    assert "operator" in gpu_block.lower() or "migration" in gpu_block.lower()


def test_gpu_instance_security_posture_private_only() -> None:
    """Pin private placement + VCN-scoped VLM ingress (no public exposure)."""
    main_tf = (OCI_ROOT / "main.tf").read_text()
    # Extract the acx_gpu_burst resource block for targeted asserts.
    start = main_tf.index('resource "oci_core_instance" "acx_gpu_burst"')
    rest = main_tf[start:]
    end = rest.find("\nresource ")
    gpu_block = rest if end < 0 else rest[:end]

    assert "assign_public_ip = false" in gpu_block
    assert "oci_core_subnet.acx_private_subnet.id" in gpu_block
    assert "prohibit_public_ip_on_vnic = true" in main_tf
    assert 'resource "oci_core_security_list" "acx_gpu_security_list"' in main_tf
    assert "oci_core_security_list.acx_gpu_security_list.id" in main_tf

    # Extract every ingress rule that opens port 8000 and require VCN-only source.
    import re

    blocks = re.findall(
        r"ingress_security_rules\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}",
        main_tf,
        flags=re.MULTILINE,
    )
    port_8000_blocks = [b for b in blocks if "min = 8000" in b]
    assert port_8000_blocks, "expected at least one port-8000 ingress rule"
    for block in port_8000_blocks:
        assert 'source      = "0.0.0.0/0"' not in block, "port 8000 must not be world-open: " + block
        assert 'source      = "10.0.0.0/16"' in block
    assert 'description = "GPU VLM endpoint from ACX VCN"' in main_tf


def test_gpu_nat_and_jump_host_ssh_present() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    assert 'resource "oci_core_nat_gateway" "acx_nat"' in main_tf
    assert "oci_core_nat_gateway.acx_nat.id" in main_tf
    assert 'resource "oci_core_route_table" "acx_private_rt"' in main_tf
    assert 'description = "SSH from acx-backend subnet"' in main_tf
    assert "min = 22" in main_tf
    # Public list must not inherit VCN-wide SSH (S2-06).
    assert 'description = "SSH from ACX VCN (jump host)"' not in main_tf


def test_gpu_endpoint_outputs_for_acx_gpu_endpoint_url() -> None:
    outputs_tf = (OCI_ROOT / "outputs.tf").read_text()
    assert 'output "gpu_private_ip"' in outputs_tf
    assert 'output "gpu_endpoint_url"' in outputs_tf
    assert "oci_core_instance.acx_gpu_burst.private_ip" in outputs_tf
    assert "http://${oci_core_instance.acx_gpu_burst.private_ip}:8000" in outputs_tf


EXPECTED_Q4_DIGEST = "7ea0a652b4bda1c1911a93a79a7cd98b92011dfea078e87328285294b2b4ab44"
EXPECTED_MMPROJ_DIGEST = "9f248089357599a08a23af40cb5ce0030de14a2e119b7ef57f66cb339bd20819"
HUB_PIN = "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639"
LOCAL_Q4 = "qwen3-vl-30b-a3b-instruct-q4.gguf"
LOCAL_MMPROJ = "qwen3-vl-30b-a3b-instruct-mmproj.gguf"


def test_gpu_cloud_init_pins_gguf_digests_from_hub_revision() -> None:
    parsed = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    entry = next(item for item in parsed["write_files"] if item["path"] == "/opt/acx-gpu/models/SHA256SUMS")
    content = entry["content"]
    digest_lines = [line for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert len(digest_lines) == 2

    digest_re = re.compile(r"^([0-9a-f]{64})  (.+)$")
    parsed_digests: dict[str, str] = {}
    for line in digest_lines:
        match = digest_re.fullmatch(line)
        assert match, f"expected sha256sum line, got {line!r}"
        parsed_digests[match.group(2)] = match.group(1)

    assert parsed_digests == {
        LOCAL_Q4: EXPECTED_Q4_DIGEST,
        LOCAL_MMPROJ: EXPECTED_MMPROJ_DIGEST,
    }
    assert HUB_PIN in content

    profiles = (REPO_ROOT / "apps" / "prototype-description-service" / "scene" / "config" / "profiles.py").read_text()
    hub_repo, model_revision = HUB_PIN.split("@", 1)
    pairs = re.findall(
        r'hub_repo="([^"]+)",\s*\n\s*model_revision="([^"]+)"',
        profiles,
    )
    qwen_pairs = [rev for repo, rev in pairs if repo == hub_repo]
    assert len(qwen_pairs) == 2, f"expected 2 profiles pinning {hub_repo}, got {len(qwen_pairs)}"
    assert all(rev == model_revision for rev in qwen_pairs), (
        f"every {hub_repo} profile must pin revision {model_revision}, got {qwen_pairs}"
    )


def test_gpu_cloud_init_bakes_qwen_measurement_candidate() -> None:
    cloud_init = (OCI_ROOT / "gpu-cloud-init.yaml").read_text()
    parsed = yaml.safe_load(cloud_init)

    assert parsed["write_files"]
    assert "Qwen3-VL-30B-A3B-Instruct" in cloud_init
    assert "/opt/acx-gpu/models" in cloud_init
    assert "qwen3-vl-30b-a3b-instruct-mmproj.gguf" in cloud_init
    assert "docker image inspect ghcr.io/ggerganov/llama.cpp:server-cuda" in cloud_init
    assert "acx-gpu-vlm.service" in cloud_init
    assert "systemctl start acx-gpu-vlm.service" in cloud_init
    assert "nvidia-container-toolkit" in cloud_init
    assert "StartLimitIntervalSec=120" in cloud_init
    assert "StartLimitBurst=3" in cloud_init


def _self_stop_script(cloud_init: dict, tmp_path: Path) -> tuple[Path, Path]:
    files = {entry["path"]: entry for entry in cloud_init["write_files"]}
    script = files["/usr/local/bin/acx-gpu-self-stop.sh"]["content"].replace("$${", "${")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env_path = tmp_path / "watchdog.env"
    env_path.write_text(
        "MAX_UPTIME_SECONDS=3600\n"
        "ACX_SELF_STOP_ENABLED=1\n"
        "ACX_SELF_STOP_FALLBACK_POWEROFF=0\n"
    )
    # Keep production commands on fixed absolute paths while allowing this
    # test to exercise the enabled branch without touching host /usr/bin.
    script = script.replace("/etc/acx-gpu-self-stop.env", str(env_path))
    script = script.replace("/usr/bin/curl", str(bin_dir / "curl"))
    script = script.replace("/usr/bin/python3", str(bin_dir / "python3"))
    script = script.replace("/usr/bin/oci", str(bin_dir / "oci"))
    # Keep failure-mode tests fast; production values remain bounded and
    # deliberately non-zero in the cloud-init template.
    script = script.replace("readonly METADATA_RETRY_DELAY_SECONDS=2", "readonly METADATA_RETRY_DELAY_SECONDS=0")
    script = script.replace("readonly STOP_RETRY_DELAY_SECONDS=5", "readonly STOP_RETRY_DELAY_SECONDS=0")
    script_path = tmp_path / "acx-gpu-self-stop.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)
    logger_log = tmp_path / "logger.log"
    (bin_dir / "logger").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {logger_log}\n")
    (bin_dir / "logger").chmod(0o755)
    return script_path, bin_dir


def test_gpu_self_stop_bakes_and_validates_fixed_runtime_dependencies() -> None:
    cloud_init = (OCI_ROOT / "gpu-cloud-init.yaml").read_text()
    parsed = yaml.safe_load(cloud_init)
    files = {entry["path"]: entry for entry in parsed["write_files"]}
    runtime_check = files["/usr/local/bin/acx-gpu-runtime-check.sh"]["content"]
    readme = files["/opt/acx-gpu/README.md"]["content"]

    assert "OCI CLI" in readme
    assert "/usr/bin/curl" in readme
    assert "/usr/bin/python3" in readme
    assert "/usr/bin/oci" in readme
    assert "test -x /usr/bin/curl" in runtime_check
    assert "test -x /usr/bin/python3" in runtime_check
    assert "test -x /usr/bin/oci" in runtime_check


def test_gpu_self_stop_enabled_path_retries_and_verifies_stopped(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    instance_id = "ocid1.instance.oc1..selfstoptest"
    action_log = tmp_path / "actions.log"
    (bin_dir / "curl").write_text("#!/bin/sh\nprintf '%s\\n' '{\"id\":\"" + instance_id + "\"}'\n")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "python3").write_text("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' '" + instance_id + "'\n")
    (bin_dir / "python3").chmod(0o755)
    (bin_dir / "oci").write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *' compute instance action '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}\n"
        "    count=$(grep -c 'compute instance action' " + str(action_log) + " 2>/dev/null || true)\n"
        "    [ \"$count\" -ge 2 ] || exit 1\n"
        "    exit 0;;\n"
        "  *' compute instance get '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}\n"
        "    printf '%s\\n' STOPPED\n"
        "    exit 0;;\n"
        "esac\n"
        "exit 9\n"
    )
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    calls = action_log.read_text().splitlines()
    assert sum("compute instance action" in call for call in calls) == 2
    assert any("--auth instance_principal" in call for call in calls)
    assert any("--wait-for-state STOPPED" in call for call in calls)
    assert any("--max-wait-seconds" in call for call in calls)
    assert any("compute instance get" in call and "--raw-output" in call for call in calls)


def _write_metadata_fakes(bin_dir: Path, instance_id: str) -> None:
    (bin_dir / "curl").write_text("#!/bin/sh\nprintf '%s\\n' '{\"id\":\"" + instance_id + "\"}'\n")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "python3").write_text("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' '" + instance_id + "'\n")
    (bin_dir / "python3").chmod(0o755)


def test_gpu_self_stop_enabled_path_retries_iam_failure_three_times(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    instance_id = "ocid1.instance.oc1..iamfailure"
    action_log = tmp_path / "actions.log"
    _write_metadata_fakes(bin_dir, instance_id)
    (bin_dir / "oci").write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *' compute instance action '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}; exit 1;;\n"
        "esac\n"
        "exit 9\n"
    )
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert len(action_log.read_text().splitlines()) == 3
    assert "OCI STOP request failed" in (tmp_path / "logger.log").read_text()
    assert "did not converge" in (tmp_path / "logger.log").read_text()


def test_gpu_self_stop_enabled_path_retries_cli_timeout(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    instance_id = "ocid1.instance.oc1..timeout"
    action_log = tmp_path / "actions.log"
    _write_metadata_fakes(bin_dir, instance_id)
    (bin_dir / "oci").write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *' compute instance action '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}; exit 124;;\n"
        "esac\n"
        "exit 9\n"
    )
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert len(action_log.read_text().splitlines()) == 3
    assert "OCI STOP request failed" in (tmp_path / "logger.log").read_text()


def test_gpu_self_stop_enabled_path_rejects_non_terminal_state(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    instance_id = "ocid1.instance.oc1..stillrunning"
    action_log = tmp_path / "actions.log"
    _write_metadata_fakes(bin_dir, instance_id)
    (bin_dir / "oci").write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        "  *' compute instance action '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}; exit 0;;\n"
        "  *' compute instance get '*)\n"
        f"    printf '%s\\n' \"$*\" >> {action_log}; printf '%s\\n' RUNNING; exit 0;;\n"
        "esac\n"
        "exit 9\n"
    )
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    calls = action_log.read_text().splitlines()
    assert sum("compute instance action" in call for call in calls) == 3
    assert sum("compute instance get" in call for call in calls) == 3
    assert "observed RUNNING, expected STOPPED" in (tmp_path / "logger.log").read_text()


def test_gpu_self_stop_enabled_path_retries_metadata_timeout(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    (bin_dir / "curl").write_text("#!/bin/sh\nexit 28\n")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "python3").write_text("#!/bin/sh\ncat >/dev/null\nexit 1\n")
    (bin_dir / "python3").chmod(0o755)
    # The CLI must exist before metadata is attempted, even though it is not
    # reached after all metadata attempts fail.
    (bin_dir / "oci").write_text("#!/bin/sh\nexit 9\n")
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    logs = (tmp_path / "logger.log").read_text()
    assert logs.count("metadata request failed") == 3
    assert "unable to read instance OCID" in logs


def test_gpu_self_stop_enabled_path_fails_closed_when_cli_missing(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    script = script_path.read_text().replace(str(bin_dir / "oci"), str(tmp_path / "missing-oci"))
    script_path.write_text(script)
    (bin_dir / "curl").write_text("#!/bin/sh\nprintf '%s\\n' '{\"id\":\"ocid1.instance.oc1..missingcli\"}'\n")
    (bin_dir / "curl").chmod(0o755)
    (bin_dir / "python3").write_text("#!/bin/sh\ncat >/dev/null\nprintf '%s\\n' 'ocid1.instance.oc1..missingcli'\n")
    (bin_dir / "python3").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "OCI CLI" in (tmp_path / "logger.log").read_text()


def test_terraform_configuration_validates() -> None:
    if shutil.which("terraform") is None:
        pytest.fail(
            "terraform binary not on PATH; the mandatory release gate is "
            "`make test-infra-terraform`"
        )

    # validate requires an initialized working directory. Initialization is
    # part of the release gate, so provider download failures must be visible
    # instead of allowing this suite to pass with validation skipped.
    if not (OCI_ROOT / ".terraform").is_dir():
        init = subprocess.run(
            ["terraform", "-chdir=infra/oci", "init", "-backend=false", "-input=false"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if init.returncode != 0:
            pytest.fail(
                "terraform init unavailable; the mandatory release gate is "
                "`make test-infra-terraform`: " + (init.stderr or init.stdout)[:400]
            )

    result = subprocess.run(
        ["terraform", "-chdir=infra/oci", "validate"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_terraform_validation_fails_when_terraform_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The VLM infrastructure suite must not turn missing Terraform into a skip."""

    monkeypatch.setattr(shutil, "which", lambda _command: None)
    with pytest.raises(pytest.fail.Exception, match="terraform"):
        try:
            test_terraform_configuration_validates()
        except pytest.skip.Exception as exc:
            raise AssertionError("missing Terraform must fail the release validation, not skip it") from exc


def test_terraform_validation_fails_when_init_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider initialization errors must remain visible to the release gate."""

    monkeypatch.setattr(shutil, "which", lambda _command: "/usr/bin/terraform")
    real_is_dir = Path.is_dir

    def no_initialized_terraform(path: Path) -> bool:
        if path == OCI_ROOT / ".terraform":
            return False
        return real_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", no_initialized_terraform)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="provider initialization unavailable"
        ),
    )

    with pytest.raises(pytest.fail.Exception, match="terraform"):
        try:
            test_terraform_configuration_validates()
        except pytest.skip.Exception as exc:
            raise AssertionError("Terraform init errors must fail the release validation, not skip it") from exc


def test_terraform_release_gate_is_mandatory_and_documented() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    provisioning = (OCI_ROOT / "GPU-BURST-PROVISIONING.md").read_text()

    target = re.search(r"^test-infra-terraform:\n((?:\t.*\n)+)", makefile, flags=re.MULTILINE)
    assert target is not None
    commands = target.group(1)
    assert "terraform -chdir=infra/oci init -backend=false" in commands
    assert "terraform -chdir=infra/oci validate" in commands
    assert "make test-infra-terraform" in provisioning
    assert "release gate" in provisioning.lower()


def test_spike_artifact_records_e19_1_measurement_fields() -> None:
    artifact_path = REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-gpu-spike-2026-07-08.json"
    artifact = json.loads(artifact_path.read_text())

    assert artifact["schema"] == "acx-gpu-spike/v1"
    assert artifact["task_ref"] == "VLM-3"
    assert artifact["shape"] == "VM.GPU.A10.1"
    assert artifact["measurement_candidate"]["model_id"] == "Qwen3-VL-30B-A3B-Instruct"
    assert artifact["measurements"]["warm_start_p95_seconds"]["target_seconds"] == 90
    assert "a10_quota_confirmed" in artifact["oci_capacity"]


def test_gpu_self_stop_watchdog_units_and_bootstrap_are_configured() -> None:
    cloud_init = (OCI_ROOT / "gpu-cloud-init.yaml").read_text()
    parsed = yaml.safe_load(cloud_init)
    files = {entry["path"]: entry for entry in parsed["write_files"]}

    service = files["/etc/systemd/system/acx-gpu-self-stop.service"]["content"]
    timer = files["/etc/systemd/system/acx-gpu-self-stop.timer"]["content"]
    script = files["/usr/local/bin/acx-gpu-self-stop.sh"]["content"]
    env = files["/etc/acx-gpu-self-stop.env"]["content"]

    assert "Type=oneshot" in service
    assert "ExecStart=/usr/local/bin/acx-gpu-self-stop.sh" in service
    assert "EnvironmentFile=-/etc/acx-gpu-self-stop.env" in service
    assert "source /etc/acx-gpu-self-stop.env" in script
    assert "OnBootSec=${max_uptime_seconds}" in timer
    # A failed service can exhaust its systemd restart burst; keep invoking the
    # watchdog on a monotonic cadence until the instance is actually stopped.
    assert "OnUnitActiveSec=${max_uptime_seconds}" in timer
    assert "AccuracySec=30s" in timer
    assert "Persistent=false" in timer
    assert "Unit=acx-gpu-self-stop.service" in timer
    assert "MAX_UPTIME_SECONDS=${max_uptime_seconds}" in env
    assert "ACX_SELF_STOP_ENABLED=${self_stop_enabled}" in env
    assert "ACX_SELF_STOP_FALLBACK_POWEROFF=1" in env
    assert "oci compute instance action" in script
    assert "--auth instance_principal" in script
    assert "ACX_SELF_STOP_ENABLED:-0" in script
    assert "systemctl poweroff" in script
    assert "ACX_SELF_STOP_FALLBACK_POWEROFF:-0" in script
    assert "Restart=on-failure" in service
    assert "RestartSec=" in service
    assert "TimeoutStartSec=" in service
    assert "--connect-timeout" in script
    assert "--max-time" in script
    assert "--wait-for-state STOPPED" in script
    assert "--max-wait-seconds" in script
    assert "compute instance get" in script
    assert "/usr/bin/oci" in script

    commands = "\n".join(parsed["runcmd"])
    assert "systemctl enable acx-gpu-self-stop.timer" in commands
    assert "systemctl start acx-gpu-self-stop.timer" in commands
    assert "systemctl is-active --quiet acx-gpu-self-stop.timer" in commands
    assert commands.index("systemctl start acx-gpu-self-stop.timer") < commands.index(
        "systemctl start acx-gpu-vlm.service"
    )


def test_gpu_self_stop_script_exits_without_stop_when_disabled(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    files = {entry["path"]: entry for entry in cloud_init["write_files"]}
    script_path = tmp_path / "acx-gpu-self-stop.sh"
    # Terraform's $${...} escape emits a literal ${...} in the rendered script.
    script = files["/usr/local/bin/acx-gpu-self-stop.sh"]["content"].replace("$${", "${")
    script_path.write_text(script)
    script_path.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "logger").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "logger").chmod(0o755)
    stop_marker = tmp_path / "stop-called"
    (bin_dir / "oci").write_text(f"#!/bin/sh\ntouch {stop_marker}\n")
    (bin_dir / "oci").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "ACX_SELF_STOP_ENABLED": "0"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not stop_marker.exists(), "disabled self-stop must not invoke the OCI stop command"


def test_gpu_self_stop_failure_uses_guest_poweroff_fallback(tmp_path: Path) -> None:
    cloud_init = yaml.safe_load((OCI_ROOT / "gpu-cloud-init.yaml").read_text())
    script_path, bin_dir = _self_stop_script(cloud_init, tmp_path)
    env_path = tmp_path / "watchdog.env"
    env_path.write_text(
        "MAX_UPTIME_SECONDS=3600\n"
        "ACX_SELF_STOP_ENABLED=1\n"
        "ACX_SELF_STOP_FALLBACK_POWEROFF=1\n"
    )
    _write_metadata_fakes(bin_dir, "ocid1.instance.oc1..fallback")
    (bin_dir / "oci").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "oci").chmod(0o755)
    poweroff_marker = tmp_path / "poweroff-called"
    (bin_dir / "systemctl").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {poweroff_marker}\n")
    (bin_dir / "systemctl").chmod(0o755)

    result = subprocess.run(
        [str(script_path)],
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert poweroff_marker.read_text().strip() == "poweroff"


def test_gpu_self_stop_terraform_wiring_and_narrow_policy_are_present() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    variables_tf = (OCI_ROOT / "variables.tf").read_text()
    outputs_tf = (OCI_ROOT / "outputs.tf").read_text()
    tfvars_example = (OCI_ROOT / "terraform.tfvars.example").read_text()
    watchdog_tf = (OCI_ROOT / "watchdog.tf").read_text()

    assert 'variable "gpu_max_uptime_seconds"' in variables_tf
    assert re.search(r'variable "gpu_max_uptime_seconds".*?default\s*=\s*3600', variables_tf, re.DOTALL)
    assert 'variable "gpu_self_stop_enabled"' in variables_tf
    assert re.search(r'variable "gpu_self_stop_enabled".*?default\s*=\s*true', variables_tf, re.DOTALL)
    assert "templatefile(\"${path.module}/gpu-cloud-init.yaml\"" in main_tf
    assert "max_uptime_seconds = var.gpu_max_uptime_seconds" in main_tf
    assert "self_stop_enabled  = var.gpu_self_stop_enabled ? 1 : 0" in main_tf
    assert "gpu_max_uptime_seconds" in tfvars_example
    assert "gpu_self_stop_enabled" in tfvars_example
    assert 'output "self_stop_dynamic_group_id"' in outputs_tf
    assert 'output "gpu_max_uptime_seconds"' in outputs_tf

    assert 'resource "oci_identity_dynamic_group" "acx_gpu_self_stop"' in watchdog_tf
    assert 'resource "oci_identity_policy" "acx_gpu_self_stop"' in watchdog_tf
    assert "instance.compartment.id" in watchdog_tf
    assert "instance.id" in watchdog_tf
    assert "in compartment id ${var.compartment_ocid}" in watchdog_tf
    assert "request.permission = 'INSTANCE_POWER_ACTIONS'" in watchdog_tf
    assert "target.instance.id = '${oci_core_instance.acx_gpu_burst.id}'" in watchdog_tf
    assert "request.permission = INSTANCE_STOP" not in watchdog_tf
    assert "INSTANCE_STOP" not in watchdog_tf
    assert "manage instances" not in watchdog_tf.lower()


def test_gpu_self_stop_policy_allows_only_targeted_read_for_verification() -> None:
    watchdog_tf = (OCI_ROOT / "watchdog.tf").read_text()

    assert "to read instances" in watchdog_tf
    assert "request.permission = 'INSTANCE_READ'" in watchdog_tf
    assert watchdog_tf.count("target.instance.id = '${oci_core_instance.acx_gpu_burst.id}'") >= 2
    # A compromised GPU principal must not be able to power-action the backend
    # or any other instance merely because it shares the parent compartment.
    assert "oci_core_instance.acx_backend.id" not in watchdog_tf
    assert "target.instance.id = '${oci_core_instance.acx_backend.id}'" not in watchdog_tf
    assert "to use instance-family" not in watchdog_tf
    assert "to manage instance-family" not in watchdog_tf


def test_gpu_self_stop_example_documents_guest_poweroff_recovery() -> None:
    tfvars_example = (OCI_ROOT / "terraform.tfvars.example").read_text()

    assert "A failed OCI stop uses the bounded guest poweroff fallback" in tfvars_example
    assert "STOPPED-by-guest" in tfvars_example
    assert "does not silently fall back" not in tfvars_example
