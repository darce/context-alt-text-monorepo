import json
import subprocess
from pathlib import Path

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
    assert 'user_data           = base64encode(file("${path.module}/gpu-cloud-init.yaml"))' in main_tf


def test_gpu_cloud_init_bakes_qwen_measurement_candidate() -> None:
    cloud_init = (OCI_ROOT / "gpu-cloud-init.yaml").read_text()
    parsed = yaml.safe_load(cloud_init)

    assert parsed["write_files"]
    assert "Qwen3-VL-30B-A3B-Instruct" in cloud_init
    assert "/opt/acx-gpu/models" in cloud_init
    assert "qwen3-vl-30b-a3b-instruct-mmproj.gguf" in cloud_init
    assert "docker image inspect ghcr.io/ggerganov/llama.cpp:server-cuda" in cloud_init
    assert "acx-gpu-vlm.service" in cloud_init
    assert "nvidia-container-toolkit" in cloud_init


def test_terraform_configuration_validates() -> None:
    result = subprocess.run(
        ["terraform", "-chdir=infra/oci", "validate"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_spike_artifact_records_e19_1_measurement_fields() -> None:
    artifact_path = REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-gpu-spike-2026-07-08.json"
    artifact = json.loads(artifact_path.read_text())

    assert artifact["schema"] == "acx-gpu-spike/v1"
    assert artifact["task_ref"] == "VLM-3"
    assert artifact["shape"] == "VM.GPU.A10.1"
    assert artifact["measurement_candidate"]["model_id"] == "Qwen3-VL-30B-A3B-Instruct"
    assert artifact["measurements"]["warm_start_p95_seconds"]["target_seconds"] == 90
    assert "a10_quota_confirmed" in artifact["oci_capacity"]
