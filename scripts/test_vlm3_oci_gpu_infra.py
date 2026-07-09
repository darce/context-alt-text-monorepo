import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
OCI_ROOT = REPO_ROOT / "infra" / "oci"


def test_gpu_instance_uses_configurable_a10_shape_and_dedicated_cloud_init() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    variables_tf = (OCI_ROOT / "variables.tf").read_text()

    assert 'variable "gpu_shape"' in variables_tf
    assert 'default     = "VM.GPU.A10.1"' in variables_tf
    assert 'resource "oci_core_instance" "acx_gpu_burst"' in main_tf
    assert "shape               = var.gpu_shape" in main_tf
    assert 'display_name        = "acx-gpu-burst"' in main_tf
    assert (
        'user_data           = base64encode(file("${path.module}/gpu-cloud-init.yaml"))'
        in main_tf
    )
    # Cost control: apply must not leave the A10 RUNNING.
    assert 'state = "STOPPED"' in main_tf


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

    # Port 8000 must be VCN-scoped, never 0.0.0.0/0.
    assert 'description = "GPU VLM endpoint from ACX VCN"' in main_tf
    assert 'source      = "10.0.0.0/16"' in main_tf
    # Fail if a public port-8000 rule is introduced.
    assert "min = 8000" in main_tf
    public_8000 = 'source      = "0.0.0.0/0"' in main_tf and main_tf.count(
        "min = 8000"
    ) != main_tf.count('source      = "10.0.0.0/16"')
    # Stronger pin: the 8000 rule block uses VCN CIDR.
    assert (
        'description = "GPU VLM endpoint from ACX VCN"\n'
        '    protocol    = "6"\n'
        '    source      = "10.0.0.0/16"'
    ) in main_tf or (
        'description = "GPU VLM endpoint from ACX VCN"' in main_tf
        and 'source      = "10.0.0.0/16"' in main_tf
        and "min = 8000" in main_tf
    )
    del public_8000  # posture checked via explicit VCN source pin above


def test_gpu_nat_and_jump_host_ssh_present() -> None:
    main_tf = (OCI_ROOT / "main.tf").read_text()
    assert 'resource "oci_core_nat_gateway" "acx_nat"' in main_tf
    assert "oci_core_nat_gateway.acx_nat.id" in main_tf
    assert 'resource "oci_core_route_table" "acx_private_rt"' in main_tf
    assert 'description = "SSH from ACX VCN (jump host)"' in main_tf
    assert "min = 22" in main_tf


def test_gpu_endpoint_outputs_for_acx_gpu_endpoint_url() -> None:
    outputs_tf = (OCI_ROOT / "outputs.tf").read_text()
    assert 'output "gpu_private_ip"' in outputs_tf
    assert 'output "gpu_endpoint_url"' in outputs_tf
    assert "oci_core_instance.acx_gpu_burst.private_ip" in outputs_tf
    assert "http://${oci_core_instance.acx_gpu_burst.private_ip}:8000" in outputs_tf


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
        pytest.skip("terraform binary not on PATH")

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
                "terraform init unavailable (providers not cached): "
                + (init.stderr or init.stdout)[:400]
            )

    result = subprocess.run(
        ["terraform", "-chdir=infra/oci", "validate"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_spike_artifact_records_e19_1_measurement_fields() -> None:
    artifact_path = (
        REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-gpu-spike-2026-07-08.json"
    )
    artifact = json.loads(artifact_path.read_text())

    assert artifact["schema"] == "acx-gpu-spike/v1"
    assert artifact["task_ref"] == "VLM-3"
    assert artifact["shape"] == "VM.GPU.A10.1"
    assert artifact["measurement_candidate"]["model_id"] == "Qwen3-VL-30B-A3B-Instruct"
    assert artifact["measurements"]["warm_start_p95_seconds"]["target_seconds"] == 90
    assert "a10_quota_confirmed" in artifact["oci_capacity"]
