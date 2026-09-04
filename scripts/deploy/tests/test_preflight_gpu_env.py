from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/preflight-gpu-env.sh"
CONTRACT = ROOT / "scripts/deploy/lib/gpu-env-contract.sh"
BOOTSTRAP = ROOT / "infra/oci/demo/bootstrap-wp.sh"
DESCRIBE_GATE = ROOT / "infra/oci/demo/lib/describe-gate.sh"
SYNC_DEMO = ROOT / "scripts/deploy/sync-demo.sh"
PRODUCER_EXAMPLE = ROOT / "apps/prototype-description-service/.env.prod.example"
DEMO_EXAMPLE = ROOT / "infra/oci/demo/.env.example"


def valid_env() -> dict[str, str]:
    return {
        "ACX_DESCRIPTION_ADAPTER": "gpu_qwen30b",
        "ACX_GPU_ENDPOINT_URL": "http://acx-gpu-burst.compute.oraclevcn.com:8000",
        "ACX_GPU_ENDPOINT_ALLOWLIST": "localhost,acx-gpu-burst,*.oraclevcn.com",
        "ACX_GPU_ENDPOINT_API_KEY": "fake-gpu-key-for-preflight-tests",
        "ACX_GPU_SNAPSHOT_DIR": "/run/acx",
        "ACX_GPU_STATE_PATH": "/run/acx/gpu-state.json",
        "ACX_GPU_STATE_STALE_SECONDS": "180",
        "ACX_RECOGNITION_URL": "https://api.altcontext.com",
        "ACX_RECOGNITION_API_KEY": "fake-tenant-key-for-preflight-tests",
        "ACX_RECOGNITION_TENANT_ID": "123e4567-e89b-42d3-a456-426614174000",
        "RECOGNITION_SECRET_BACKEND": "env",
    }


def env_text(values: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def run_preflight(
    tmp_path: Path,
    producer: dict[str, str] | None = None,
    demo: dict[str, str] | None = None,
    *,
    producer_text: str | None = None,
    demo_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    producer_file = tmp_path / "producer.env"
    demo_file = tmp_path / "demo.env"
    producer_file.write_text(
        producer_text if producer_text is not None else env_text(producer or valid_env()),
        encoding="utf-8",
    )
    demo_file.write_text(
        demo_text if demo_text is not None else env_text(demo or valid_env()),
        encoding="utf-8",
    )
    return subprocess.run(
        [str(SCRIPT), str(producer_file), str(demo_file)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("adapter", ["", "seeded", "unknown"])
def test_01_rejects_empty_seeded_and_unknown_adapters(tmp_path: Path, adapter: str) -> None:
    producer = valid_env()
    producer["ACX_DESCRIPTION_ADAPTER"] = adapter

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [1] producer ACX_DESCRIPTION_ADAPTER" in result.stderr
    assert "florence_small, gpu_qwen30b, or gpu_qwen30b_ensemble" in result.stderr


@pytest.mark.parametrize("endpoint", ["", "acx-gpu:8000", "ftp://acx-gpu", "https://"])
def test_02_gpu_adapter_requires_http_endpoint(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [2] producer ACX_GPU_ENDPOINT_URL" in result.stderr
    assert "http:// or https://" in result.stderr


@pytest.mark.parametrize("credential", ["", "replace-with-a10-endpoint-key", "<paste-key>"])
def test_03_env_backend_requires_real_api_key(tmp_path: Path, credential: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_API_KEY"] = credential

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [3] producer env backend" in result.stderr
    assert f"redacted length={len(credential)}" in result.stderr
    if credential:
        assert credential not in result.stderr


def test_03_vault_backend_accepts_map_reference_and_blank_direct_value(tmp_path: Path) -> None:
    producer = valid_env()
    producer.update(
        {
            "RECOGNITION_SECRET_BACKEND": "oci_vault",
            "RECOGNITION_VAULT_SECRET_MAP": (
                '{"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.fakegpuendpointkey"}'
            ),
            "ACX_GPU_ENDPOINT_API_KEY": "",
        }
    )

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode == 0, result.stderr


def test_03_vault_backend_rejects_direct_value_even_with_valid_map(tmp_path: Path) -> None:
    producer = valid_env()
    producer.update(
        {
            "RECOGNITION_SECRET_BACKEND": "oci_vault",
            "RECOGNITION_VAULT_SECRET_MAP": (
                '{"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.fakegpuendpointkey"}'
            ),
            "ACX_GPU_ENDPOINT_API_KEY": "PLAINTEXT_GPU_SECRET_DO_NOT_PRINT",
        }
    )

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [3] producer oci_vault backend" in result.stderr
    assert "PLAINTEXT_GPU_SECRET_DO_NOT_PRINT" not in result.stderr


@pytest.mark.parametrize(
    "vault_map",
    [
        "{}",
        '{"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1..REPLACE"}',
        '{"ACX_GPU_ENDPOINT_API_KEY":"not-an-ocid"}',
    ],
)
def test_03_vault_backend_rejects_missing_placeholder_or_invalid_reference(tmp_path: Path, vault_map: str) -> None:
    producer = valid_env()
    producer.update(
        {
            "RECOGNITION_SECRET_BACKEND": "oci_vault",
            "RECOGNITION_VAULT_SECRET_MAP": vault_map,
            "ACX_GPU_ENDPOINT_API_KEY": "",
        }
    )

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [3] producer oci_vault backend" in result.stderr
    assert vault_map not in result.stderr


@pytest.mark.parametrize(
    ("snapshot_dir", "state_path"),
    [("", "/run/acx/gpu-state.json"), ("/run/acx", ""), ("/run/acx", "/run/other/gpu-state.json")],
)
def test_04_snapshot_dir_and_state_path_must_agree(tmp_path: Path, snapshot_dir: str, state_path: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_SNAPSHOT_DIR"] = snapshot_dir
    producer["ACX_GPU_STATE_PATH"] = state_path

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [4] producer ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH" in result.stderr


@pytest.mark.parametrize("stale_seconds", ["", "0", "00", "-1", "1.5", "soon"])
def test_05_stale_seconds_must_be_a_positive_integer(tmp_path: Path, stale_seconds: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_STATE_STALE_SECONDS"] = stale_seconds

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [5] producer ACX_GPU_STATE_STALE_SECONDS" in result.stderr


@pytest.mark.parametrize(
    "missing_key",
    ["ACX_RECOGNITION_URL", "ACX_RECOGNITION_API_KEY", "ACX_RECOGNITION_TENANT_ID"],
)
def test_06_demo_recognition_config_is_required(tmp_path: Path, missing_key: str) -> None:
    demo = valid_env()
    demo[missing_key] = ""

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo recognition config" in result.stderr
    assert missing_key in result.stderr


@pytest.mark.parametrize("url", ["api.altcontext.com", "ftp://api.altcontext.com", "https://"])
def test_06_recognition_url_shape_is_validated(tmp_path: Path, url: str) -> None:
    demo = valid_env()
    demo["ACX_RECOGNITION_URL"] = url

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_URL" in result.stderr
    if url != "https://":
        assert url not in result.stderr


@pytest.mark.parametrize(
    "tenant_id",
    [
        "tenant-one",
        "00000000-0000-0000-0000-000000000000",
        "00000000-0000-4000-8000-000000000001",
    ],
)
def test_06_tenant_id_must_be_rfc4122_uuid(tmp_path: Path, tenant_id: str) -> None:
    demo = valid_env()
    demo["ACX_RECOGNITION_TENANT_ID"] = tenant_id

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_TENANT_ID" in result.stderr
    assert tenant_id not in result.stderr


def test_06_recognition_placeholder_is_rejected_without_disclosure(tmp_path: Path) -> None:
    demo = valid_env()
    placeholder = "replace-with-tenant-api-key"
    demo["ACX_RECOGNITION_API_KEY"] = placeholder

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_API_KEY" in result.stderr
    assert placeholder not in result.stderr


@pytest.mark.parametrize(
    ("key", "unsafe_value"),
    [
        ("ACX_DESCRIPTION_ADAPTER", "seeded"),
        ("ACX_GPU_ENDPOINT_URL", "ftp://unsafe.invalid"),
        ("ACX_GPU_ENDPOINT_API_KEY", "replace-with-a10-endpoint-key"),
    ],
)
def test_07_duplicate_contract_keys_are_rejected(tmp_path: Path, key: str, unsafe_value: str) -> None:
    producer = valid_env()
    text = env_text(producer) + f"{key}={unsafe_value}\n"

    result = run_preflight(tmp_path, producer_text=text)

    assert result.returncode != 0
    assert f"ERROR [7] producer env contains duplicate {key}" in result.stderr
    assert unsafe_value not in result.stderr


@pytest.mark.parametrize(
    "key",
    [
        "ACX_DESCRIPTION_ADAPTER",
        "ACX_GPU_ENDPOINT_URL",
        "ACX_GPU_ENDPOINT_API_KEY",
        "ACX_GPU_SNAPSHOT_DIR",
        "ACX_GPU_STATE_PATH",
        "ACX_GPU_STATE_STALE_SECONDS",
    ],
)
def test_08_mismatched_flip_halves_are_rejected(tmp_path: Path, key: str) -> None:
    demo = valid_env()
    replacements = {
        "ACX_DESCRIPTION_ADAPTER": "gpu_qwen30b_ensemble",
        "ACX_GPU_ENDPOINT_URL": "https://10.0.0.2:8000",
        "ACX_GPU_ENDPOINT_API_KEY": "different-fake-gpu-key",
        "ACX_GPU_SNAPSHOT_DIR": "/run/acx-other",
        "ACX_GPU_STATE_PATH": "/run/acx/gpu-state-other.json",
        "ACX_GPU_STATE_STALE_SECONDS": "181",
    }
    demo[key] = replacements[key]
    if key == "ACX_GPU_SNAPSHOT_DIR":
        demo["ACX_GPU_STATE_PATH"] = "/run/acx-other/gpu-state.json"

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert f"ERROR [8] producer and demo {key} values differ" in result.stderr
    assert replacements[key] not in result.stderr


@pytest.mark.parametrize("error_number", range(1, 10))
def test_every_numbered_error_path_redacts_sentinel_secrets(tmp_path: Path, error_number: int) -> None:
    producer = valid_env()
    demo = valid_env()
    gpu_secret = "GPU_SECRET_DO_NOT_PRINT"
    recognition_secret = "RECOGNITION_SECRET_DO_NOT_PRINT"
    producer["ACX_GPU_ENDPOINT_API_KEY"] = gpu_secret
    demo["ACX_GPU_ENDPOINT_API_KEY"] = gpu_secret
    producer["ACX_RECOGNITION_API_KEY"] = recognition_secret
    demo["ACX_RECOGNITION_API_KEY"] = recognition_secret
    producer_text = None

    if error_number == 1:
        producer["ACX_DESCRIPTION_ADAPTER"] = "seeded"
    elif error_number == 2:
        producer["ACX_GPU_ENDPOINT_URL"] = "ftp://gpu.invalid"
    elif error_number == 3:
        producer["ACX_GPU_ENDPOINT_API_KEY"] = f"replace-{gpu_secret}"
    elif error_number == 4:
        producer["ACX_GPU_STATE_PATH"] = "/run/other/gpu-state.json"
    elif error_number == 5:
        producer["ACX_GPU_STATE_STALE_SECONDS"] = "invalid"
    elif error_number == 6:
        demo["ACX_RECOGNITION_API_KEY"] = f"replace-{recognition_secret}"
    elif error_number == 7:
        producer_text = env_text(producer) + "ACX_GPU_STATE_STALE_SECONDS=999\n"
    elif error_number == 8:
        demo["ACX_GPU_STATE_STALE_SECONDS"] = "181"
    elif error_number == 9:
        producer["ACX_GPU_ENDPOINT_URL"] = "https://public.example.com/gpu"

    result = run_preflight(
        tmp_path,
        producer=producer,
        demo=demo,
        producer_text=producer_text,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert f"ERROR [{error_number}]" in result.stderr
    assert gpu_secret not in output
    assert recognition_secret not in output


def test_producer_does_not_require_plugin_recognition_config(tmp_path: Path) -> None:
    producer = valid_env()
    del producer["ACX_RECOGNITION_URL"]
    del producer["ACX_RECOGNITION_API_KEY"]
    del producer["ACX_RECOGNITION_TENANT_ID"]

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://10.20.30.40:8000",
        "http://127.0.0.1:8000",
        "http://acx-gpu-burst:8000",
        "https://worker.compute.oraclevcn.com:8000",
    ],
)
def test_09_accepts_private_or_allowlisted_gpu_endpoint(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    demo = valid_env()
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint
    demo["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, producer=producer, demo=demo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "endpoint",
    ["https://example.com/gpu", "http://8.8.8.8:8000", "http://172.32.0.1:8000"],
)
def test_09_rejects_public_gpu_endpoint(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [9] producer ACX_GPU_ENDPOINT_URL" in result.stderr
    assert endpoint not in result.stderr


def test_09_honors_producer_endpoint_allowlist(tmp_path: Path) -> None:
    producer = valid_env()
    demo = valid_env()
    producer["ACX_GPU_ENDPOINT_ALLOWLIST"] = "gpu-??.internal.example"
    producer["ACX_GPU_ENDPOINT_URL"] = "https://gpu-a1.internal.example:8000"
    demo["ACX_GPU_ENDPOINT_URL"] = "https://gpu-a1.internal.example:8000"

    result = run_preflight(tmp_path, producer=producer, demo=demo)

    assert result.returncode == 0, result.stderr


def test_wordpress_config_extra_supplies_demo_recognition_constants(tmp_path: Path) -> None:
    demo = valid_env()
    del demo["ACX_RECOGNITION_URL"]
    del demo["ACX_RECOGNITION_API_KEY"]
    del demo["ACX_RECOGNITION_TENANT_ID"]
    demo["WORDPRESS_CONFIG_EXTRA"] = (
        "define('ACX_RECOGNITION_URL','https://api.altcontext.com'); "
        "define('ACX_RECOGNITION_API_KEY','fake-tenant-key-for-preflight-tests'); "
        "define('ACX_RECOGNITION_TENANT_ID','123e4567-e89b-42d3-a456-426614174000');"
    )

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode == 0, result.stderr


def test_unchanged_producer_example_placeholder_is_rejected(tmp_path: Path) -> None:
    producer_text = PRODUCER_EXAMPLE.read_text(encoding="utf-8")

    result = run_preflight(tmp_path, producer_text=producer_text)

    assert result.returncode != 0
    assert "ERROR [3] producer oci_vault backend" in result.stderr


def test_unchanged_demo_example_placeholder_is_rejected(tmp_path: Path) -> None:
    producer = valid_env()
    demo_text = DEMO_EXAMPLE.read_text(encoding="utf-8")

    result = run_preflight(tmp_path, producer=producer, demo_text=demo_text)

    assert result.returncode != 0
    assert "ERROR [3] demo env backend" in result.stderr


def test_happy_path_prints_one_line_summary(tmp_path: Path) -> None:
    result = run_preflight(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "OK: GPU env preflight passed (producer+demo, adapter=gpu_qwen30b).\n"


def trusted_results(contract: Path, function: str) -> list[str]:
    profiles = ["florence_small", "gpu_qwen30b", "gpu_qwen30b_ensemble", "seeded", ""]
    command = (
        f"source {contract}; "
        f"for profile in florence_small gpu_qwen30b gpu_qwen30b_ensemble seeded ''; do "
        f"if {function} \"$profile\"; then printf 'yes\\n'; else printf 'no\\n'; fi; done"
    )
    result = subprocess.run(["bash", "-c", command], cwd=ROOT, text=True, capture_output=True, check=True)
    assert len(result.stdout.splitlines()) == len(profiles)
    return result.stdout.splitlines()


def trusted_allowlist(contract: Path) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; printf "%s" "$ACX_TRUSTED_DESCRIBE_PROFILES"',
            "contract-parity-test",
            str(contract),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


def test_repository_and_staged_contract_have_one_definition_and_runtime_parity(tmp_path: Path) -> None:
    staged_lib = tmp_path / "lib"
    staged_lib.mkdir()
    staged_contract = staged_lib / "gpu-env-contract.sh"
    staged_gate = staged_lib / "describe-gate.sh"
    contract_text = CONTRACT.read_text(encoding="utf-8")
    staged_contract.write_text(contract_text, encoding="utf-8")
    staged_gate.write_text(DESCRIBE_GATE.read_text(encoding="utf-8"), encoding="utf-8")

    assert 'ACX_TRUSTED_DESCRIBE_PROFILES="' not in contract_text
    assert trusted_allowlist(staged_contract) == trusted_allowlist(staged_gate)
    assert trusted_results(staged_contract, "acx_is_trusted_describe_profile") == trusted_results(
        staged_gate, "is_trusted_describe_profile"
    )


def test_staged_bootstrap_layout_contains_every_runtime_dependency(tmp_path: Path) -> None:
    sync_text = SYNC_DEMO.read_text(encoding="utf-8")
    bootstrap_text = BOOTSTRAP.read_text(encoding="utf-8")
    staged_demo = tmp_path / "demo"
    staged_lib = staged_demo / "lib"
    staged_lib.mkdir(parents=True)
    (staged_demo / "bootstrap-wp.sh").write_text(bootstrap_text, encoding="utf-8")
    (staged_lib / "describe-gate.sh").write_text(DESCRIBE_GATE.read_text(encoding="utf-8"), encoding="utf-8")

    assert 'source "$(dirname "${BASH_SOURCE[0]}")/lib/describe-gate.sh"' in bootstrap_text
    assert "gpu-env-contract.sh" not in "\n".join(
        line for line in bootstrap_text.splitlines() if line.lstrip().startswith("source ")
    )
    assert '$SCP "$DESCRIBE_GATE_SRC"' in sync_text
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1/lib/describe-gate.sh"; is_trusted_describe_profile gpu_qwen30b',
            "staged-bootstrap-test",
            str(staged_demo),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("example", [PRODUCER_EXAMPLE, DEMO_EXAMPLE])
def test_worked_examples_document_gpu_burst_profile_and_preflight(example: Path) -> None:
    text = example.read_text(encoding="utf-8")

    assert "# --- GPU burst profile (demo) ---" in text
    assert "preflight-gpu-env.sh" in text


def test_worked_examples_form_valid_pair_after_documented_replacements(tmp_path: Path) -> None:
    producer_text = PRODUCER_EXAMPLE.read_text(encoding="utf-8").replace(
        '"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1..REPLACE_GPU_ENDPOINT_KEY"',
        '"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.fakegpuendpointkey"',
    )
    demo_text = (
        DEMO_EXAMPLE.read_text(encoding="utf-8")
        .replace("replace-with-a10-endpoint-key", "fake-gpu-key-for-preflight-tests")
        .replace("replace-with-tenant-api-key", "fake-tenant-key-for-preflight-tests")
        .replace("00000000-0000-4000-8000-000000000001", "123e4567-e89b-42d3-a456-426614174000")
    )

    result = run_preflight(tmp_path, producer_text=producer_text, demo_text=demo_text)

    assert result.returncode == 0, result.stderr
