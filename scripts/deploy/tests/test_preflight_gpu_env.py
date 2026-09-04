from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/preflight-gpu-env.sh"
CONTRACT = ROOT / "scripts/deploy/lib/gpu-env-contract.sh"
BOOTSTRAP = ROOT / "infra/oci/demo/bootstrap-wp.sh"


def valid_env() -> dict[str, str]:
    return {
        "ACX_DESCRIPTION_ADAPTER": "gpu_qwen30b",
        "ACX_GPU_ENDPOINT_URL": "http://acx-gpu-burst.compute.oraclevcn.com:8000",
        "ACX_GPU_ENDPOINT_API_KEY": "test-gpu-secret",
        "ACX_GPU_SNAPSHOT_DIR": "/run/acx",
        "ACX_GPU_STATE_PATH": "/run/acx/gpu-state.json",
        "ACX_GPU_STATE_STALE_SECONDS": "180",
        "ACX_RECOGNITION_URL": "https://api.altcontext.com",
        "ACX_RECOGNITION_API_KEY": "test-recognition-secret",
        "ACX_RECOGNITION_TENANT_ID": "00000000-0000-4000-8000-000000000001",
    }


def run_preflight(tmp_path: Path, values: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / "flip.env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return subprocess.run(
        [str(SCRIPT), str(env_file)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("adapter", ["", "seeded", "unknown"])
def test_01_rejects_empty_seeded_and_unknown_adapters(tmp_path: Path, adapter: str) -> None:
    values = valid_env()
    values["ACX_DESCRIPTION_ADAPTER"] = adapter

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [1] ACX_DESCRIPTION_ADAPTER" in result.stderr
    assert "florence_small, gpu_qwen30b, or gpu_qwen30b_ensemble" in result.stderr


@pytest.mark.parametrize("endpoint", ["", "acx-gpu:8000", "ftp://acx-gpu"])
def test_02_gpu_adapter_requires_http_endpoint(tmp_path: Path, endpoint: str) -> None:
    values = valid_env()
    values["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [2] ACX_GPU_ENDPOINT_URL" in result.stderr
    assert "http:// or https://" in result.stderr


def test_03_endpoint_requires_api_key(tmp_path: Path) -> None:
    values = valid_env()
    values["ACX_GPU_ENDPOINT_API_KEY"] = ""

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [3] ACX_GPU_ENDPOINT_API_KEY" in result.stderr
    assert "redacted length=0" in result.stderr


@pytest.mark.parametrize(
    ("snapshot_dir", "state_path"),
    [("", "/run/acx/gpu-state.json"), ("/run/acx", ""), ("/run/acx", "/run/other/gpu-state.json")],
)
def test_04_snapshot_dir_and_state_path_must_agree(
    tmp_path: Path, snapshot_dir: str, state_path: str
) -> None:
    values = valid_env()
    values["ACX_GPU_SNAPSHOT_DIR"] = snapshot_dir
    values["ACX_GPU_STATE_PATH"] = state_path

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [4] ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH" in result.stderr
    assert "same directory" in result.stderr


@pytest.mark.parametrize("stale_seconds", ["", "0", "00", "-1", "1.5", "soon"])
def test_05_stale_seconds_must_be_a_positive_integer(tmp_path: Path, stale_seconds: str) -> None:
    values = valid_env()
    values["ACX_GPU_STATE_STALE_SECONDS"] = stale_seconds

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [5] ACX_GPU_STATE_STALE_SECONDS" in result.stderr
    assert "positive integer" in result.stderr


@pytest.mark.parametrize(
    "missing_key",
    ["ACX_RECOGNITION_URL", "ACX_RECOGNITION_API_KEY", "ACX_RECOGNITION_TENANT_ID"],
)
def test_06_demo_recognition_config_is_required(tmp_path: Path, missing_key: str) -> None:
    values = valid_env()
    values[missing_key] = ""

    result = run_preflight(tmp_path, values)

    assert result.returncode != 0
    assert "ERROR [6] demo recognition config" in result.stderr
    assert missing_key in result.stderr


def test_secret_values_are_never_printed(tmp_path: Path) -> None:
    values = valid_env()
    gpu_secret = "GPU_SECRET_DO_NOT_PRINT"
    recognition_secret = "RECOGNITION_SECRET_DO_NOT_PRINT"
    values["ACX_GPU_ENDPOINT_API_KEY"] = gpu_secret
    values["ACX_RECOGNITION_API_KEY"] = recognition_secret
    values["ACX_GPU_STATE_STALE_SECONDS"] = "invalid"

    result = run_preflight(tmp_path, values)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert gpu_secret not in output
    assert recognition_secret not in output


def test_wordpress_config_extra_can_supply_demo_recognition_constants(tmp_path: Path) -> None:
    values = valid_env()
    del values["ACX_RECOGNITION_URL"]
    del values["ACX_RECOGNITION_API_KEY"]
    del values["ACX_RECOGNITION_TENANT_ID"]
    values["WORDPRESS_CONFIG_EXTRA"] = (
        "define('ACX_RECOGNITION_URL','https://api.altcontext.com'); "
        "define('ACX_RECOGNITION_API_KEY','test-recognition-secret'); "
        "define('ACX_RECOGNITION_TENANT_ID','00000000-0000-4000-8000-000000000001');"
    )

    result = run_preflight(tmp_path, values)

    assert result.returncode == 0, result.stderr


def test_happy_path_prints_one_line_summary(tmp_path: Path) -> None:
    result = run_preflight(tmp_path, valid_env())

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "OK: GPU env preflight passed (adapter=gpu_qwen30b).\n"


def test_bootstrap_and_preflight_share_deploy_allowlist_contract() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")

    assert 'ACX_TRUSTED_DESCRIBE_PROFILES="florence_small gpu_qwen30b gpu_qwen30b_ensemble"' in contract
    assert 'source "${DEMO_DIR}/lib/gpu-env-contract.sh"' in bootstrap
    assert "Trusted service profiles: ${ACX_TRUSTED_DESCRIBE_PROFILES}." in bootstrap


@pytest.mark.parametrize(
    "example",
    [
        ROOT / "infra/oci/demo/.env.example",
        ROOT / "apps/prototype-description-service/.env.prod.example",
    ],
)
def test_worked_examples_include_validated_gpu_burst_profile(example: Path) -> None:
    text = example.read_text(encoding="utf-8")

    assert "# --- GPU burst profile (demo) ---" in text
    assert "scripts/deploy/preflight-gpu-env.sh" in text
    for key in (
        "ACX_DESCRIPTION_ADAPTER",
        "ACX_GPU_ENDPOINT_URL",
        "ACX_GPU_ENDPOINT_API_KEY",
        "ACX_GPU_SNAPSHOT_DIR",
        "ACX_GPU_STATE_PATH",
        "ACX_GPU_STATE_STALE_SECONDS",
        "ACX_RECOGNITION_URL",
        "ACX_RECOGNITION_API_KEY",
        "ACX_RECOGNITION_TENANT_ID",
    ):
        assert f"{key}=" in text or f"define('{key}'" in text
