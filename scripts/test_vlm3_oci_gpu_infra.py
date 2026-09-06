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


def test_terraform_configuration_validates() -> None:
    if shutil.which("terraform") is None:
        pytest.skip(
            "developer check: terraform binary not on PATH; "
            "run `make test-infra-terraform` for the mandatory release gate"
        )

    # validate requires an initialized working directory; skip cleanly when
    # providers have not been downloaded (no cloud credentials / no init).
    if not (OCI_ROOT / ".terraform").is_dir():
        init = subprocess.run(
            ["terraform", "-chdir=infra/oci", "init", "-backend=false", "-input=false"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        if init.returncode != 0:
            pytest.skip(
                "developer check: terraform init unavailable; "
                "run `make test-infra-terraform` for the mandatory release gate: " + (init.stderr or init.stdout)[:400]
            )

    result = subprocess.run(
        ["terraform", "-chdir=infra/oci", "validate"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


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
    assert "AccuracySec=30s" in timer
    assert "Persistent=false" in timer
    assert "Unit=acx-gpu-self-stop.service" in timer
    assert "MAX_UPTIME_SECONDS=${max_uptime_seconds}" in env
    assert "ACX_SELF_STOP_ENABLED=${self_stop_enabled}" in env
    assert "ACX_SELF_STOP_FALLBACK_POWEROFF=0" in env
    assert "oci compute instance action" in script
    assert "--auth instance_principal" in script
    assert "ACX_SELF_STOP_ENABLED:-0" in script
    assert "systemctl poweroff" in script
    assert "ACX_SELF_STOP_FALLBACK_POWEROFF:-0" in script

    commands = "\n".join(parsed["runcmd"])
    assert "systemctl enable acx-gpu-self-stop.timer" in commands
    assert "systemctl start acx-gpu-self-stop.timer" in commands


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
    assert "INSTANCE_STOP" in watchdog_tf
    assert "where request.permission = INSTANCE_STOP" in watchdog_tf
    assert "manage instances" not in watchdog_tf.lower()
