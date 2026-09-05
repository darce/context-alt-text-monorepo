from __future__ import annotations

import json
import hashlib
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/preflight-gpu-env.sh"
CONTRACT = ROOT / "scripts/deploy/lib/gpu-env-contract.sh"
VERIFY_LIVE_GPU = ROOT / "scripts/deploy/lib/verify-live-gpu.sh"
BOOTSTRAP = ROOT / "infra/oci/demo/bootstrap-wp.sh"
DESCRIBE_GATE = ROOT / "infra/oci/demo/lib/describe-gate.sh"
SYNC_DEMO = ROOT / "scripts/deploy/sync-demo.sh"
PRODUCER_EXAMPLE = ROOT / "apps/prototype-description-service/.env.prod.example"
DEMO_EXAMPLE = ROOT / "infra/oci/demo/.env.example"


def wordpress_config(
    *,
    url: str = "https://api.altcontext.com",
    api_key: str = "fake-tenant-key-for-preflight-tests",
    tenant_id: str = "123e4567-e89b-42d3-a456-426614174000",
    comma_padding: str = "",
) -> str:
    return (
        f"define('ACX_RECOGNITION_URL',{comma_padding}'{url}'); "
        f"define('ACX_RECOGNITION_API_KEY',{comma_padding}'{api_key}'); "
        f"define('ACX_RECOGNITION_TENANT_ID',{comma_padding}'{tenant_id}');"
    )


def valid_env() -> dict[str, str]:
    return {
        "ACX_DESCRIPTION_ADAPTER": "gpu_qwen30b",
        "ACX_GPU_ENDPOINT_URL": "http://acx-gpu-burst.compute.oraclevcn.com:8000",
        "ACX_GPU_ENDPOINT_ALLOWLIST": "localhost,acx-gpu-burst,*.oraclevcn.com",
        "ACX_GPU_ENDPOINT_API_KEY": "fake-gpu-key-for-preflight-tests",
        "ACX_GPU_CONNECT_TIMEOUT_SECONDS": "5",
        "ACX_GPU_READ_TIMEOUT_SECONDS": "175",
        "ACX_GPU_MAX_CONCURRENT_CALLS": "4",
        "ACX_GPU_WARMUP_TIMEOUT_SECONDS": "510",
        "ACX_GPU_PROMPT_VERSION": "3",
        "ACX_GPU_SNAPSHOT_DIR": "/run/acx",
        "ACX_GPU_STATE_PATH": "/run/acx/gpu-state.json",
        "ACX_GPU_STATE_STALE_SECONDS": "180",
        "WORDPRESS_CONFIG_EXTRA": wordpress_config(),
        "RECOGNITION_SECRET_BACKEND": "env",
    }


def valid_demo_env() -> dict[str, str]:
    values = valid_env()
    del values["ACX_GPU_ENDPOINT_API_KEY"]
    return values


def env_text(values: dict[str, str]) -> str:
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def run_preflight(
    tmp_path: Path,
    producer: dict[str, str] | None = None,
    demo: dict[str, str] | None = None,
    *,
    producer_text: str | None = None,
    demo_text: str | None = None,
    check_reaper: bool = False,
    systemctl_script: str | None = None,
    dns_address: str | None = None,
) -> subprocess.CompletedProcess[str]:
    producer_file = tmp_path / "producer.env"
    demo_file = tmp_path / "demo.env"
    producer_file.write_text(
        producer_text if producer_text is not None else env_text(producer or valid_env()),
        encoding="utf-8",
    )
    demo_file.write_text(
        demo_text if demo_text is not None else env_text(demo or valid_demo_env()),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    getent = fake_bin / "getent"
    getent.write_text(
        """#!/usr/bin/env bash
host="${2:-}"
case "$host" in
  localhost) echo '127.0.0.1 STREAM localhost' ;;
  acx-gpu-burst|*.oraclevcn.com|gpu-a1.internal.example) echo '10.0.0.20 STREAM private' ;;
  public-allowed.example) echo '93.184.216.34 STREAM public' ;;
  mixed-allowed.example) printf '10.0.0.20 STREAM private\\n93.184.216.34 STREAM public\\n' ;;
  unresolved-allowed.example) exit 2 ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    if dns_address is not None:
        getent.write_text("#!/usr/bin/env bash\nprintf '%s STREAM fake\\n' " + '"$FAKE_DNS_ADDRESS"\n')
    getent.chmod(0o755)
    if systemctl_script is not None:
        systemctl = fake_bin / "systemctl"
        systemctl.write_text(systemctl_script, encoding="utf-8")
        systemctl.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    if dns_address is not None:
        env["FAKE_DNS_ADDRESS"] = dns_address
    args = [str(SCRIPT)]
    if check_reaper:
        args.append("--check-reaper")
    args.extend([str(producer_file), str(demo_file)])
    return subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def live_gpu_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "adapter": "gpu",
        "tier": "final_gpu",
        "cached": False,
        "model_id": ("unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639"),
        "model_version": "Q4_K_M",
        "prompt_or_task_version": "3",
        "alt_text_draft": "A blue and red gradient.",
    }
    payload.update(overrides)
    return payload


def run_live_gpu_verifier(
    tmp_path: Path,
    *,
    payload: dict[str, object] | None = None,
    curl_status: int = 0,
    enqueue_payload: dict[str, object] | None = None,
    poll_response: dict[str, object] | None = None,
    timeout_seconds: int | None = None,
    clock_step_seconds: int | None = None,
    wordpress_config_extra: str | None = None,
    enforce_bsd_mktemp: bool = False,
    final_newline: bool = True,
) -> subprocess.CompletedProcess[str]:
    staged_lib = tmp_path / "lib"
    staged_lib.mkdir()
    staged_verifier = staged_lib / "verify-live-gpu.sh"
    staged_verifier.write_text(VERIFY_LIVE_GPU.read_text(encoding="utf-8"), encoding="utf-8")
    staged_verifier.chmod(0o700)
    (staged_lib / "gpu-env-contract.sh").write_text(CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    (staged_lib / "describe-gate.sh").write_text(DESCRIBE_GATE.read_text(encoding="utf-8"), encoding="utf-8")
    demo_env = tmp_path / "demo.env"
    demo_env.write_text(
        f"WORDPRESS_CONFIG_EXTRA={wordpress_config_extra or wordpress_config()}" + ("\n" if final_newline else ""),
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
output_file=
url=
printf '%s\\0' "$@" >> "$FAKE_CURL_ARGV_LOG"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) output_file="$2"; shift 2 ;;
    --config) test -f "$2"; shift 2 ;;
    -F)
      image_path="${2#*=@}"
      cp "${image_path%;type=image/png}" "$FAKE_SMOKE_IMAGE"
      shift 2 ;;
    --form-string)
      case "$2" in media_ids=*) printf '%s' "${2#media_ids=}" > "$FAKE_MEDIA_IDS" ;; esac
      shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
[[ "${FAKE_CURL_STATUS}" == 0 ]] || exit "${FAKE_CURL_STATUS}"
test -n "$output_file"
printf '%s\n' "$url" >> "$FAKE_CURL_LOG"
case "$url" in
  */scene/describe/run) printf '%s' "$FAKE_CURL_ENQUEUE_RESPONSE" > "$output_file" ;;
  */scene/describe/run/*/items)
    python3 - "$output_file" <<'RESULT'
import json, os, sys
payload = json.loads(os.environ["FAKE_CURL_ITEM"])
media_id = json.load(open(os.environ["FAKE_MEDIA_IDS"]))[0]
json.dump({"run_id": "123e4567-e89b-42d3-a456-426614174999", "items": [{
    "media_id": media_id, "status": "completed", "tier": payload.pop("tier"),
    "alt_text_draft": payload.pop("alt_text_draft"), "provenance": payload,
}]}, open(sys.argv[1], "w"))
RESULT
    ;;
  */scene/describe/run/*) printf '%s' "$FAKE_CURL_RESPONSE" > "$output_file" ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o700)
    if enforce_bsd_mktemp:
        fake_mktemp = fake_bin / "mktemp"
        fake_mktemp.write_text(
            """#!/usr/bin/env bash
case "$1" in *XXXXXX) ;; *) echo 'BSD mktemp requires trailing XXXXXX' >&2; exit 64 ;; esac
/usr/bin/mktemp "$1"
""",
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o700)
    if clock_step_seconds is not None:
        fake_date = fake_bin / "date"
        fake_date.write_text(
            """#!/usr/bin/env bash
test "$1" = +%s
current=1000
if [[ -f "$FAKE_DATE_COUNTER" ]]; then
  current="$(<"$FAKE_DATE_COUNTER")"
fi
printf '%s\n' "$((current + FAKE_DATE_STEP))" > "$FAKE_DATE_COUNTER"
printf '%s\n' "$current"
""",
            encoding="utf-8",
        )
        fake_date.chmod(0o700)
        fake_sleep = fake_bin / "sleep"
        fake_sleep.write_text('#!/usr/bin/env bash\n/bin/sleep "$1"\n', encoding="utf-8")
        fake_sleep.chmod(0o700)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_CURL_STATUS": str(curl_status),
            "FAKE_CURL_ITEM": json.dumps(payload or live_gpu_payload()),
            "FAKE_MEDIA_IDS": str(tmp_path / "media_ids.json"),
            "FAKE_SMOKE_IMAGE": str(tmp_path / "smoke.png"),
            "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
            "FAKE_CURL_ARGV_LOG": str(tmp_path / "curl-argv.log"),
            "FAKE_CURL_ENQUEUE_RESPONSE": json.dumps(
                enqueue_payload
                or {
                    "run_id": "123e4567-e89b-42d3-a456-426614174999",
                    "status": "pending",
                    "tier": None,
                    "result_generation": 0,
                    "visual_facts": None,
                    "error": None,
                }
            ),
            "FAKE_CURL_RESPONSE": json.dumps(
                poll_response
                if poll_response is not None
                else {
                    "run_id": "123e4567-e89b-42d3-a456-426614174999",
                    "status": "completed",
                    "total": 1,
                    "completed": 1,
                    "failed": 0,
                    "tier": "final_gpu",
                    "result_generation": 2,
                    "visual_facts": payload or live_gpu_payload(),
                    "error": None,
                }
            ),
        }
    )
    if timeout_seconds is not None:
        env["LIVE_GPU_POLL_TIMEOUT_SECONDS"] = str(timeout_seconds)
    if clock_step_seconds is not None:
        env["FAKE_DATE_COUNTER"] = str(tmp_path / "date.counter")
        env["FAKE_DATE_STEP"] = str(clock_step_seconds)
    process = subprocess.Popen(
        [str(staged_verifier), str(demo_env)],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        pytest.fail("live GPU verifier exceeded the 30-second harness watchdog")
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


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


def test_03_env_backend_rejects_whitespace_only_api_key(tmp_path: Path) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_API_KEY"] = " \t "

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [3] producer env backend" in result.stderr


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


def test_03_demo_rejects_unused_gpu_endpoint_secret(tmp_path: Path) -> None:
    demo = valid_demo_env()
    secret = "UNUSED_GPU_SECRET_DO_NOT_PRINT"
    demo["ACX_GPU_ENDPOINT_API_KEY"] = secret

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [3] demo ACX_GPU_ENDPOINT_API_KEY must be absent" in result.stderr
    assert secret not in result.stderr


def test_03_producer_rejects_api_key_containing_only_unicode_whitespace(tmp_path: Path) -> None:
    producer = valid_env()
    unicode_whitespace = "\u00a0"
    producer["ACX_GPU_ENDPOINT_API_KEY"] = unicode_whitespace

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [3] producer env backend" in result.stderr
    assert unicode_whitespace not in result.stdout + result.stderr


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
    "vault_map",
    [
        '{"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.valid",}',
        '["ocid1.vaultsecret.oc1.iad.valid"]',
        '{"ACX_GPU_ENDPOINT_API_KEY":42}',
        (
            '{"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.first",'
            '"ACX_GPU_ENDPOINT_API_KEY":"ocid1.vaultsecret.oc1.iad.second"}'
        ),
    ],
)
def test_03_vault_backend_parses_complete_unique_string_map(tmp_path: Path, vault_map: str) -> None:
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


@pytest.mark.parametrize("backend", ["", "ENV", "file", "env-with-fallback", "oci_vault "])
def test_03_secret_backend_is_an_exact_allowlist(tmp_path: Path, backend: str) -> None:
    producer = valid_env()
    producer["RECOGNITION_SECRET_BACKEND"] = backend

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "RECOGNITION_SECRET_BACKEND must be exactly env or oci_vault" in result.stderr


@pytest.mark.parametrize(
    ("snapshot_dir", "state_path"),
    [
        ("", "/run/acx/gpu-state.json"),
        ("/run/acx", ""),
        ("/run/acx", "/run/other/gpu-state.json"),
        ("/tmp/not-mounted", "/tmp/not-mounted/not-the-runtime-file.json"),
        ("/run/acx", "/run/acx/not-the-runtime-file.json"),
        ("/run/acx/", "/run/acx/gpu-state.json"),
    ],
)
def test_04_snapshot_dir_and_state_path_must_agree(tmp_path: Path, snapshot_dir: str, state_path: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_SNAPSHOT_DIR"] = snapshot_dir
    producer["ACX_GPU_STATE_PATH"] = state_path

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [4] producer ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH" in result.stderr


@pytest.mark.parametrize("stale_seconds", ["", "0", "00", "-1", "1.5", "soon", "9" * 316])
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
    demo = valid_demo_env()
    values = {
        "ACX_RECOGNITION_URL": "https://api.altcontext.com",
        "ACX_RECOGNITION_API_KEY": "fake-tenant-key-for-preflight-tests",
        "ACX_RECOGNITION_TENANT_ID": "123e4567-e89b-42d3-a456-426614174000",
    }
    values[missing_key] = ""
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(
        url=values["ACX_RECOGNITION_URL"],
        api_key=values["ACX_RECOGNITION_API_KEY"],
        tenant_id=values["ACX_RECOGNITION_TENANT_ID"],
    )

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo recognition config" in result.stderr
    assert missing_key in result.stderr


@pytest.mark.parametrize(
    "url",
    [
        "api.altcontext.com",
        "ftp://api.altcontext.com",
        "https://",
        "https://api.altcontext.com?redirect=untrusted",
        "https://api.altcontext.com#untrusted",
    ],
)
def test_06_recognition_url_shape_is_validated(tmp_path: Path, url: str) -> None:
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(url=url)

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
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(tenant_id=tenant_id)

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_TENANT_ID" in result.stderr
    assert tenant_id not in result.stderr


def test_06_recognition_placeholder_is_rejected_without_disclosure(tmp_path: Path) -> None:
    demo = valid_demo_env()
    placeholder = "replace-with-tenant-api-key"
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(api_key=placeholder)

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_API_KEY" in result.stderr
    assert placeholder not in result.stderr


def test_06_recognition_key_containing_only_unicode_whitespace_is_rejected(tmp_path: Path) -> None:
    demo = valid_demo_env()
    unicode_whitespace = "\u00a0"
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(api_key=unicode_whitespace)

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo ACX_RECOGNITION_API_KEY" in result.stderr
    assert unicode_whitespace not in result.stdout + result.stderr


def test_06_php_defines_inside_block_comments_do_not_supply_config(tmp_path: Path) -> None:
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = (
        "define('ACX_RECOGNITION_URL','https://api.altcontext.com'); "
        "/* define('ACX_RECOGNITION_API_KEY','commented-key'); */ "
        "define('ACX_RECOGNITION_TENANT_ID','123e4567-e89b-42d3-a456-426614174000');"
    )

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "demo recognition config is incomplete" in result.stderr
    assert "ACX_RECOGNITION_API_KEY" in result.stderr
    assert "commented-key" not in result.stderr


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
    "unsafe_line",
    [
        "ACX_DESCRIPTION_ADAPTER = seeded",
        " ACX_DESCRIPTION_ADAPTER=seeded",
        "export ACX_DESCRIPTION_ADAPTER=seeded",
    ],
)
def test_07_rejects_compose_assignments_outside_canonical_subset(tmp_path: Path, unsafe_line: str) -> None:
    result = run_preflight(
        tmp_path,
        producer_text=env_text(valid_env()) + f"{unsafe_line}\n",
    )

    assert result.returncode != 0
    assert "ERROR [7] producer env" in result.stderr
    assert "canonical KEY=value" in result.stderr or "duplicate" in result.stderr
    assert "seeded" not in result.stderr


@pytest.mark.parametrize(
    "value",
    ["${GPU_ADAPTER}", "gpu_qwen30b # effective value differs"],
)
def test_07_rejects_interpolation_and_inline_comments(tmp_path: Path, value: str) -> None:
    producer = valid_env()
    producer["ACX_DESCRIPTION_ADAPTER"] = value

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [7] producer env ACX_DESCRIPTION_ADAPTER" in result.stderr


def test_quoted_exact_values_use_compose_value(tmp_path: Path) -> None:
    producer = valid_env()
    demo = valid_demo_env()
    producer["ACX_DESCRIPTION_ADAPTER"] = '"gpu_qwen30b"'
    demo["ACX_DESCRIPTION_ADAPTER"] = '"gpu_qwen30b"'

    result = run_preflight(tmp_path, producer=producer, demo=demo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "key",
    [
        "ACX_DESCRIPTION_ADAPTER",
        "ACX_GPU_ENDPOINT_URL",
        "ACX_GPU_STATE_STALE_SECONDS",
    ],
)
def test_08_mismatched_flip_halves_are_rejected(tmp_path: Path, key: str) -> None:
    demo = valid_demo_env()
    replacements = {
        "ACX_DESCRIPTION_ADAPTER": "gpu_qwen30b_ensemble",
        "ACX_GPU_ENDPOINT_URL": "https://10.0.0.2:8000",
        "ACX_GPU_STATE_STALE_SECONDS": "181",
    }
    demo[key] = replacements[key]

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert f"ERROR [8] producer and demo {key} values differ" in result.stderr
    assert replacements[key] not in result.stderr


@pytest.mark.parametrize("error_number", range(1, 10))
def test_every_numbered_error_path_redacts_sentinel_secrets(tmp_path: Path, error_number: int) -> None:
    producer = valid_env()
    demo = valid_demo_env()
    gpu_secret = "GPU_SECRET_DO_NOT_PRINT"
    recognition_secret = "RECOGNITION_SECRET_DO_NOT_PRINT"
    producer["ACX_GPU_ENDPOINT_API_KEY"] = gpu_secret
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(api_key=recognition_secret)
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
        demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(api_key=f"replace-{recognition_secret}")
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
    del producer["WORDPRESS_CONFIG_EXTRA"]

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://10.20.30.40:8000",
        "http://acx-gpu-burst:8000",
        "https://worker.compute.oraclevcn.com:8000",
    ],
)
def test_09_accepts_private_or_allowlisted_gpu_endpoint(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    demo = valid_demo_env()
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


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://169.254.169.254",
        "http://[fe80::1]:8000",
        "http://[::ffff:169.254.169.254]:8000",
        "http://[::ffff:a9fe:a9fe]:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
        "http://0.0.0.0:8000",
        "http://[::]:8000",
        "http://[::ffff:127.0.0.1]:8000",
        "http://localhost:8000",
    ],
)
def test_09_rejects_link_local_gpu_endpoint(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint

    demo = valid_demo_env()
    demo["ACX_GPU_ENDPOINT_URL"] = endpoint
    result = run_preflight(tmp_path, producer=producer, demo=demo)

    assert result.returncode != 0
    assert "ERROR [9] producer ACX_GPU_ENDPOINT_URL" in result.stderr
    assert endpoint not in result.stderr


@pytest.mark.parametrize("address", ["::ffff:169.254.169.254", "::ffff:a9fe:a9fe", "::1", "0.0.0.0"])
def test_09_rejects_unsafe_resolved_gpu_address(tmp_path: Path, address: str) -> None:
    result = run_preflight(tmp_path, dns_address=address)
    assert result.returncode != 0
    assert "ERROR [9] producer ACX_GPU_ENDPOINT_URL" in result.stderr


@pytest.mark.parametrize(
    "endpoint",
    ["https://acx-gpu-burst:not-a-port", "https://:8000", "https://acx-gpu-burst:0"],
)
def test_02_rejects_malformed_authority_or_port(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [2] producer ACX_GPU_ENDPOINT_URL" in result.stderr
    assert endpoint not in result.stderr


def test_09_honors_producer_endpoint_allowlist(tmp_path: Path) -> None:
    producer = valid_env()
    demo = valid_demo_env()
    producer["ACX_GPU_ENDPOINT_ALLOWLIST"] = "gpu-??.internal.example"
    producer["ACX_GPU_ENDPOINT_URL"] = "https://gpu-a1.internal.example:8000"
    demo["ACX_GPU_ENDPOINT_URL"] = "https://gpu-a1.internal.example:8000"

    result = run_preflight(tmp_path, producer=producer, demo=demo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://public-allowed.example:8000",
        "https://mixed-allowed.example:8000",
        "https://unresolved-allowed.example:8000",
    ],
)
def test_09_allowlisted_hostname_requires_all_private_dns_answers(tmp_path: Path, endpoint: str) -> None:
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_ALLOWLIST"] = "*.example"
    producer["ACX_GPU_ENDPOINT_URL"] = endpoint

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [9] producer ACX_GPU_ENDPOINT_URL" in result.stderr
    assert endpoint not in result.stderr


def test_demo_rejects_stale_standalone_recognition_values(tmp_path: Path) -> None:
    demo = valid_demo_env()
    demo["ACX_RECOGNITION_URL"] = "https://stale-but-valid.example"
    demo["ACX_RECOGNITION_API_KEY"] = "stale-key-that-must-not-win"
    demo["ACX_RECOGNITION_TENANT_ID"] = "123e4567-e89b-42d3-a456-426614174001"
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(api_key="replace-with-operative-key")

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode != 0
    assert "ERROR [6] demo standalone ACX_RECOGNITION_* entries are ambiguous" in result.stderr
    assert "stale-key-that-must-not-win" not in result.stderr
    assert "replace-with-operative-key" not in result.stderr


def test_preflight_accepts_literal_php_define_whitespace(tmp_path: Path) -> None:
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config(comma_padding=" ")

    result = run_preflight(tmp_path, demo=demo)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ACX_GPU_CONNECT_TIMEOUT_SECONDS", "nan"),
        ("ACX_GPU_READ_TIMEOUT_SECONDS", "inf"),
        ("ACX_GPU_MAX_CONCURRENT_CALLS", "1.5"),
        ("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "3601"),
        ("ACX_GPU_ENDPOINT_ALLOWLIST", "valid.example, bad pattern"),
        ("ACX_GPU_PROMPT_VERSION", ""),
    ],
)
def test_10_rejects_invalid_runtime_gpu_setting(tmp_path: Path, key: str, value: str) -> None:
    producer = valid_env()
    producer[key] = value

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert f"ERROR [10] producer {key}" in result.stderr
    if value:
        assert value not in result.stderr


def test_10_rejects_whitespace_only_prompt_version(tmp_path: Path) -> None:
    producer = valid_env()
    producer["ACX_GPU_PROMPT_VERSION"] = " \t "

    result = run_preflight(tmp_path, producer=producer)

    assert result.returncode != 0
    assert "ERROR [10] producer ACX_GPU_PROMPT_VERSION" in result.stderr


def reaper_systemctl_script(
    environment_file: Path,
    *,
    reap_timer_active: bool = True,
    start_timer_active: bool = True,
    exec_start: str | None = None,
    environment_files: str | None = None,
    working_directory: Path = ROOT,
    unset_environment: str = "",
    timer_target: str = "acx-gpu-reap.service",
) -> str:
    oci = environment_file.parent / "oci-stub"
    oci.write_text("#!/bin/sh\n[ \"$1\" = --help ] || exit 9\nprintf 'Oracle Cloud Infrastructure CLI\\n'\n")
    oci.chmod(0o755)
    lease_path = environment_file.parent / "running-since.json"
    reap_active_result = "exit 0" if reap_timer_active else "exit 3"
    start_active_result = "exit 0" if start_timer_active else "exit 3"
    exec_start = exec_start or (
        "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -m infra.oci.gpu_lifecycle "
        "--mode reap --instance-id ${GPU_INSTANCE_ID} "
        "--max-lease-seconds ${MAX_LEASE_SECONDS} --load-dir /run/acx-write "
        f"--running-since-path {lease_path} --oci-bin {oci} ; ignore_errors=no ; }}"
    )
    if "--oci-bin" not in exec_start:
        exec_start = exec_start.replace(" ; ignore_errors=", f" --oci-bin {oci} ; ignore_errors=")
    if "--running-since-path" not in exec_start:
        exec_start = exec_start.replace(" ; ignore_errors=", f" --running-since-path {lease_path} ; ignore_errors=")
    environment_files = environment_files or f"{environment_file} (ignore_errors=no)"
    return f"""#!/usr/bin/env bash
if [[ "$1" == show && "$2" == acx-gpu-reap.timer ]]; then
    printf '%s\n' 'Unit={timer_target}'
    exit 0
fi
case "$1:$3" in
  is-enabled:acx-gpu-reap.timer|is-enabled:acx-gpu-start.timer) exit 0 ;;
  is-active:acx-gpu-reap.timer) {reap_active_result} ;;
  is-active:acx-gpu-start.timer) {start_active_result} ;;
  show:*)
    cat <<'PROPERTIES'
User={pwd.getpwuid(os.geteuid()).pw_name}
ExecStart={exec_start}
WorkingDirectory={working_directory}
FragmentPath=/etc/systemd/system/acx-gpu-reap.service
DropInPaths=
EnvironmentFiles={environment_files}
UnsetEnvironment={unset_environment}
PROPERTIES
    ;;
  *) exit 2 ;;
esac
"""


@pytest.mark.parametrize("executable", ["/usr/bin/true", "/bin/false"])
def test_11_reaper_preflight_rejects_executable_argv_mismatch(tmp_path: Path, executable: str) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    unit = reaper_systemctl_script(reaper_env).replace("path=/usr/bin/python3", f"path={executable}")
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    assert result.returncode != 0
    assert "structurally valid GPU lifecycle reaper" in result.stderr
    assert "MANUAL STOP" not in result.stdout


@pytest.mark.parametrize("assignment", [
    " MAX_LEASE_SECONDS=0", "\tMAX_LEASE_SECONDS=0", "\rMAX_LEASE_SECONDS=0", ' MAX_LEASE_SECONDS="0"',
    "MAX_LEASE_SECONDS =0", "MAX_LEASE_SECONDS=3600\\\nMAX_LEASE_SECONDS=0",
])
def test_11_reaper_preflight_rejects_ambiguous_systemd_assignment(tmp_path: Path, assignment: str) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n" + assignment + "\n"
    )
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(reaper_env))
    assert result.returncode != 0
    assert "EnvironmentFile must use canonical" in result.stderr
    assert "MANUAL STOP" not in result.stdout


def test_11_reaper_preflight_accepts_quoted_last_wins_systemd_assignment(tmp_path: Path) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        '# generated environment\nGPU_INSTANCE_ID="ocid1.instance.oc1.iad.fakeinstance"\n'
        "MAX_LEASE_SECONDS=0\nMAX_LEASE_SECONDS='3600'\n"
    )
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(reaper_env))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("custom_registry", [False, True])
def test_11_installer_payload_passes_reaper_preflight(tmp_path: Path, custom_registry: bool) -> None:
    installer = (ROOT / "scripts/deploy/gpu-lifecycle-install.sh").read_text()
    staging = installer.split('run_with_deadline "remote release staging"', 1)[1]
    staging = 'run_with_deadline "remote release staging"' + staging.split(
        'run_with_deadline "remote release validation and switch"', 1
    )[0]
    service_root = tmp_path / "service"
    registry = ROOT / "scripts/deploy/gpu-snapshot-deployments.conf"
    if custom_registry:
        registry = tmp_path / "custom deployments.conf"
        registry.write_text("dev\ndev-fir\nstaging\nprod\ncustom-production\n")
    # Run the actual staging commands with local transports and no privileges.
    # No installer startup, OCI calls, units, or live host are exercised.
    staging = staging.replace("/etc/acx", str(tmp_path / "etc-acx"))
    staging = staging.replace("/opt/acx-gpu", str(tmp_path / "opt-acx-gpu"))
    result = subprocess.run(
        ["bash", "-c", r'''
set -eu
repo_root=$1
remote_stage=$2
DEPLOYMENTS_FILE=$3
HOST=local
SSH_OPTIONS=(-o BatchMode=yes)
run_with_deadline() { shift; "$@"; }
sudo() { if [ "$1" != chown ]; then "$@"; fi; }
ssh() { shift 2; eval "$2"; }
scp() {
    shift 3 # -q -o BatchMode=yes
    local destination="${!#}"
    set -- "${@:1:$#-1}" "${destination#local:}"
    cp "$@"
}
''' + staging, "installer-payload", str(ROOT), str(service_root), str(registry)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    shipped_registry = service_root / "scripts/deploy/gpu-snapshot-deployments.conf"
    assert shipped_registry.read_bytes() == registry.read_bytes()
    monitored = subprocess.run(
        [sys.executable, "-c", "from pathlib import Path; "
         "from infra.oci.gpu_lifecycle import load_source; "
         "assert Path(load_source.__file__).resolve().is_relative_to(Path.cwd()); "
         "print('\\n'.join(load_source.AggregateJobLoadSource(Path('/run/acx'), 180).expected_environments))"],
        cwd=service_root, env=dict(os.environ, PYTHONPATH=str(service_root)),
        text=True, capture_output=True, check=False,
    )
    assert monitored.returncode == 0, monitored.stderr
    assert set(monitored.stdout.splitlines()) == set(registry.read_text().splitlines())
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(
        reaper_env, working_directory=service_root,
    ))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("custom_registry", [False, True])
def test_11_installer_release_identity_includes_deployment_registry(tmp_path: Path, custom_registry: bool) -> None:
    installer = (ROOT / "scripts/deploy/gpu-lifecycle-install.sh").read_text()
    identity = installer.split("release_id=$(", 1)[1].split("\nremote_release=", 1)[0]
    source_root = tmp_path / "source"
    lifecycle = source_root / "infra/oci/gpu_lifecycle"
    lifecycle.mkdir(parents=True)
    (lifecycle / "reaper.py").write_text("# unchanged module\n")
    registry = source_root / "scripts/deploy/gpu-snapshot-deployments.conf"
    registry.parent.mkdir(parents=True)
    registry.write_text("prod\n")
    if custom_registry:
        registry = tmp_path / "custom deployments.conf"

    def release_id() -> str:
        result = subprocess.run(
            ["bash", "-ec", 'repo_root=$1\nDEPLOYMENTS_FILE=$2\nrelease_id=$(' + identity + '\nprintf "%s" "$release_id"',
             "release-identity", str(source_root), str(registry)],
            text=True, capture_output=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    registry.write_text("# registry version one\n")
    original = release_id()
    registry.write_text("# registry version two\n")
    assert release_id() != original


@pytest.mark.parametrize("registry_content", [None, "invalid registry\n"])
def test_11_reaper_preflight_validates_service_deployment_registry(tmp_path: Path, registry_content: str | None) -> None:
    service_root = tmp_path / "service"
    shutil.copytree(ROOT / "infra/oci/gpu_lifecycle", service_root / "infra/oci/gpu_lifecycle")
    # Preserve regular-package boundaries so Python cannot fall back to the
    # verification checkout when importing the staged service.
    for relative in ("infra/__init__.py", "infra/oci/__init__.py"):
        shutil.copyfile(ROOT / relative, service_root / relative)
    registry = service_root / "scripts/deploy/gpu-snapshot-deployments.conf"
    registry.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/deploy/gpu-snapshot-deployments.conf", registry)
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    unit = reaper_systemctl_script(reaper_env, working_directory=service_root)
    control = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    assert control.returncode == 0, control.stderr
    if registry_content is None:
        registry.unlink()
    else:
        registry.write_text(registry_content)
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    assert result.returncode != 0
    assert "structurally valid GPU lifecycle reaper" in result.stderr
    assert "MANUAL STOP" not in result.stdout


@pytest.mark.parametrize("installed_options", [False, True])
def test_11_reaper_preflight_proves_timer_target_and_stop_fallback(tmp_path: Path, installed_options: bool) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )

    systemctl = reaper_systemctl_script(reaper_env)
    if installed_options:
        with reaper_env.open("a") as stream:
            stream.write("IDLE_SECONDS=300\nACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS=600\n")
        systemctl = systemctl.replace(
            " ; ignore_errors=no",
            (
                " --load-stale-grace-seconds ${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS}"
                " --gpu-state-json /run/acx/gpu-state.json"
                " --idle-seconds ${IDLE_SECONDS} --fence-delay-seconds 2 --probe-oci"
                " ; ignore_errors=no"
            ),
        )

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=systemctl,
    )

    assert result.returncode == 0, result.stderr
    assert "MANUAL STOP fallback: oci compute instance action --action STOP" in result.stdout
    assert "ocid1.instance.oc1.iad.fakeinstance" in result.stdout
    assert result.stdout.endswith("OK: GPU env preflight passed (producer+demo, adapter=gpu_qwen30b).\n")


def test_11_reaper_preflight_fails_closed_when_timer_is_inactive(tmp_path: Path) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(reaper_env, reap_timer_active=False),
    )

    assert result.returncode != 0
    assert "ERROR [11] acx-gpu-reap.timer must be enabled and active" in result.stderr


def test_11_reaper_preflight_fails_closed_when_start_timer_is_inactive(tmp_path: Path) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(reaper_env, start_timer_active=False),
    )

    assert result.returncode != 0
    assert "ERROR [11] acx-gpu-start.timer must be enabled and active" in result.stderr


def test_11_reaper_preflight_rejects_non_reaper_execstart(tmp_path: Path) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(reaper_env, exec_start="/bin/true"),
    )

    assert result.returncode != 0
    assert "ERROR [11] acx-gpu-reap.service ExecStart" in result.stderr


def test_11_reaper_preflight_rejects_required_text_inside_one_label_argument(tmp_path: Path) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )
    disguised_arguments = (
        "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -m infra.oci.gpu_lifecycle "
        '--mode reap --label "--instance-id ${GPU_INSTANCE_ID} '
        '--max-lease-seconds ${MAX_LEASE_SECONDS}" ; ignore_errors=no ; }'
    )

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(reaper_env, exec_start=disguised_arguments),
    )

    assert result.returncode != 0
    assert "structurally valid GPU lifecycle reaper" in result.stderr


@pytest.mark.parametrize(
    "suffix",
    [
        "--mode start",
        "--mode=start",
        "--mo start",
        "--max-lease-seconds=0",
        "--dry-run",
        "--dry",
        "--unknown",
        "--instance-state STOPPED",
    ],
)
def test_11_reaper_preflight_rejects_a_second_effective_mode(tmp_path: Path, suffix: str) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )
    trailing_mode = (
        "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 -m infra.oci.gpu_lifecycle "
        "--mode reap --instance-id ${GPU_INSTANCE_ID} "
        "--max-lease-seconds ${MAX_LEASE_SECONDS} --load-dir /run/acx-write " + suffix + " ; ignore_errors=no ; }"
    )

    control = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(
            reaper_env, exec_start=trailing_mode.replace(" " + suffix + " ;", " ;")
        ),
    )
    assert control.returncode == 0, control.stderr

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(reaper_env, exec_start=trailing_mode),
    )

    assert result.returncode != 0
    assert "structurally valid GPU lifecycle reaper" in result.stderr
    assert "MANUAL STOP" not in result.stdout


def test_11_reaper_preflight_honors_all_environment_files_in_order(tmp_path: Path) -> None:
    base_env = tmp_path / "base.env"
    base_env.write_text(
        "GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n",
        encoding="utf-8",
    )
    override_env = tmp_path / "override.env"
    override_env.write_text("MAX_LEASE_SECONDS=86401\n", encoding="utf-8")
    environment_files = f"{base_env} (ignore_errors=no) {override_env} (ignore_errors=no)"

    result = run_preflight(
        tmp_path,
        check_reaper=True,
        systemctl_script=reaper_systemctl_script(
            base_env,
            environment_files=environment_files,
        ),
    )

    assert result.returncode != 0
    assert "MAX_LEASE_SECONDS must be in 1..86400" in result.stderr


def test_wordpress_config_extra_supplies_demo_recognition_constants(tmp_path: Path) -> None:
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = wordpress_config()

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
    assert "ERROR [6] demo ACX_RECOGNITION_API_KEY" in result.stderr


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
    preflight_text = SCRIPT.read_text(encoding="utf-8")
    staged_contract.write_text(contract_text, encoding="utf-8")
    staged_gate.write_text(DESCRIBE_GATE.read_text(encoding="utf-8"), encoding="utf-8")

    assert 'ACX_TRUSTED_DESCRIBE_PROFILES="' not in contract_text
    assert "php_define_value()" not in preflight_text
    assert trusted_allowlist(staged_contract) == trusted_allowlist(staged_gate)
    assert trusted_results(staged_contract, "acx_is_trusted_describe_profile") == trusted_results(
        staged_gate, "is_trusted_describe_profile"
    )


def bootstrap_contract_block() -> str:
    text = BOOTSTRAP.read_text(encoding="utf-8")
    return text.split("# BOOTSTRAP_GPU_CONTRACT_BEGIN\n", 1)[1].split("# BOOTSTRAP_GPU_CONTRACT_END", 1)[0]


def test_explicitly_staged_bootstrap_contract_loads(tmp_path: Path) -> None:
    staged_demo = tmp_path / "demo"
    staged_lib = staged_demo / "lib"
    staged_lib.mkdir(parents=True)
    (staged_lib / "describe-gate.sh").write_text(DESCRIBE_GATE.read_text())
    (staged_lib / "gpu-env-contract.sh").write_text(CONTRACT.read_text())
    bootstrap = staged_demo / "bootstrap-wp.sh"
    bootstrap.write_text(
        "set -euo pipefail\n" + bootstrap_contract_block() + "is_trusted_describe_profile gpu_qwen30b\n"
    )
    result = subprocess.run(["bash", str(bootstrap)], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("wrapper", ['"{}";', "if (false) {{ {} }}", "\u00a0{}", "{} define('EXTRA',09);"])
def test_php_nonexecuting_defines_fail_closed(tmp_path: Path, wrapper: str) -> None:
    demo = valid_demo_env()
    demo["WORDPRESS_CONFIG_EXTRA"] = wrapper.format(wordpress_config())
    result = run_preflight(tmp_path, demo=demo)
    assert result.returncode != 0
    assert "recognition config is incomplete" in result.stderr or "dotenv" in result.stderr


@pytest.mark.parametrize("envelope", ["", '"'])
def test_bootstrap_and_preflight_read_the_same_active_php_key(tmp_path: Path, envelope: str) -> None:
    config = "/* define('ACX_RECOGNITION_API_KEY','obsolete-key'); */ " + wordpress_config()
    demo = valid_demo_env()
    config = envelope + config + envelope
    demo["WORDPRESS_CONFIG_EXTRA"] = config
    result = run_preflight(tmp_path, demo=demo)
    assert result.returncode == 0, result.stderr
    staged = tmp_path / "demo"
    (staged / "lib").mkdir(parents=True)
    (staged / "lib/describe-gate.sh").write_text(DESCRIBE_GATE.read_text())
    (staged / "lib/gpu-env-contract.sh").write_text(CONTRACT.read_text())
    bootstrap = staged / "bootstrap-wp.sh"
    bootstrap.write_text(
        'set -euo pipefail\nWORDPRESS_CONFIG_EXTRA="$1"\n'
        + bootstrap_contract_block()
        + 'php_define_value ACX_RECOGNITION_API_KEY "$(acx_env_literal_value "$WORDPRESS_CONFIG_EXTRA")"\n'
    )
    result = subprocess.run(["bash", str(bootstrap), config], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fake-tenant-key-for-preflight-tests"


def test_producer_example_documents_every_runtime_gpu_setting() -> None:
    text = PRODUCER_EXAMPLE.read_text(encoding="utf-8")

    for key in (
        "ACX_GPU_CONNECT_TIMEOUT_SECONDS",
        "ACX_GPU_READ_TIMEOUT_SECONDS",
        "ACX_GPU_MAX_CONCURRENT_CALLS",
        "ACX_GPU_WARMUP_TIMEOUT_SECONDS",
        "ACX_GPU_ENDPOINT_ALLOWLIST",
        "ACX_GPU_PROMPT_VERSION",
    ):
        assert f"{key}=" in text


def test_demo_example_does_not_duplicate_gpu_endpoint_secret() -> None:
    text = DEMO_EXAMPLE.read_text(encoding="utf-8")

    assert not any(line.startswith("ACX_GPU_ENDPOINT_API_KEY=") for line in text.splitlines())


def test_runbook_requires_reaper_fail_fast_and_checksum_bound_reviewed_artifact() -> None:
    runbook = (ROOT / "docs/runbooks/gpu-demo-env-flip.md").read_text(encoding="utf-8")
    bash_blocks = runbook.split("```bash\n")[1:]

    assert bash_blocks
    assert all(block.startswith("set -euo pipefail\n") for block in bash_blocks)
    assert "preflight-gpu-env.sh --check-reaper" in runbook
    assert "MANUAL STOP fallback" in runbook
    assert "ls -t dist/alt-context-*.zip" not in runbook
    assert "PLUGIN_ZIP_SHA256=replace-with-reviewed-sha256" in runbook
    assert 'shasum -a 256 "$PLUGIN_ZIP"' in runbook
    assert "printf 'Deploying reviewed plugin artifact: %s\\n'" in runbook
    assert "oci compute instance action --action STOP" in runbook


@pytest.mark.parametrize("tampered", [False, True])
def test_runbook_deploys_the_checksum_bound_artifact_not_newest_mtime(tmp_path: Path, tampered: bool) -> None:
    runbook = (ROOT / "docs/runbooks/gpu-demo-env-flip.md").read_text(encoding="utf-8")
    deploy_block = runbook.split("## 3. Deploy in producer-then-consumer order", 1)[1]
    deploy_block = deploy_block.split("```bash\n", 1)[1].split("```", 1)[0]
    reviewed = tmp_path / "dist/alt-context-reviewed.zip"
    unreviewed = tmp_path / "dist/alt-context-unreviewed.zip"
    reviewed.parent.mkdir()
    reviewed.write_bytes(b"reviewed")
    unreviewed.write_bytes(b"unreviewed")
    os.utime(reviewed, (1, 1))
    os.utime(unreviewed, (2, 2))
    reviewed_sha256 = subprocess.run(
        ["shasum", "-a", "256", str(reviewed)],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.split()[0]
    deploy_block = deploy_block.replace(
        "CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod", ":"
    ).replace("replace-with-reviewed-sha256", reviewed_sha256)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_ssh.chmod(0o700)
    if tampered:
        reviewed.write_bytes(b"tampered after review")
    fake_make = fake_bin / "make"
    fake_make.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\' "$PLUGIN_ZIP" > "$MAKE_ARTIFACT_LOG"\n',
        encoding="utf-8",
    )
    fake_make.chmod(0o700)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["MAKE_ARTIFACT_LOG"] = str(tmp_path / "artifact.log")

    result = subprocess.run(["bash"], input=deploy_block, cwd=tmp_path, env=env, text=True, capture_output=True)

    if tampered:
        assert result.returncode != 0
        assert not (tmp_path / "artifact.log").exists()
        return
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "artifact.log").read_text(encoding="utf-8") == str(reviewed.relative_to(tmp_path))


def test_runbook_final_verification_requires_uncached_live_gpu_inference() -> None:
    runbook = (ROOT / "docs/runbooks/gpu-demo-env-flip.md").read_text(encoding="utf-8")
    final_verification = runbook.split("## 4. Verify and close the change", 1)[1]
    verifier = VERIFY_LIVE_GPU.read_text(encoding="utf-8")

    assert "verify-live-gpu.sh /opt/acx-backend/demo/secrets/.env" in final_verification
    assert "/scene/describe/run" in verifier
    assert "/scene/describe/run/" in verifier
    assert "/scene/describe/multipart" not in verifier
    assert '--form-string "recognition_enabled=false"' in verifier
    assert 'payload.get("adapter") != "gpu"' in verifier
    assert 'payload.get("tier") != "final_gpu"' in verifier
    assert 'payload.get("cached") is not False' in verifier
    assert (
        'payload.get("model_id") != expected_model_id' in verifier
        and "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639" in verifier
    )
    assert 'payload.get("model_version") != "Q4_K_M"' in verifier
    assert 'payload.get("prompt_or_task_version") != "3"' in verifier
    assert 'payload.get("alt_text_draft")' in verifier
    assert final_verification.index("verify-live-gpu.sh /opt") < final_verification.index(
        "rm -f /tmp/acx-gpu-preflight/preflight-gpu-env.sh"
    )
    final_bash = final_verification.split("```bash\n", 1)[1].split("```", 1)[0]
    syntax = subprocess.run(["bash", "-n"], input=final_bash, text=True, capture_output=True, check=False)
    assert syntax.returncode == 0, syntax.stderr


def run_stop_block(
    tmp_path: Path, *, process_status: int = 1, cancel: bool = False, lease: str | None = None,
    occupied: bool = False, lease_status: int | None = None,
) -> subprocess.CompletedProcess[str]:
    runbook = (ROOT / "docs/runbooks/gpu-demo-env-flip.md").read_text()
    block = runbook.rsplit("```bash\n", 1)[1].split("```", 1)[0]
    remote = tmp_path / "remote"
    remote.mkdir()
    if lease:
        (remote / lease).touch()
    if occupied:
        (remote / "activity.lock").mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    scripts = {
        "terraform": "printf '%s\\n' ocid1.instance.oc1.iad.test",
        # Execute every rendered command; only remap the fake filesystem root.
        # mkdir/rmdir/test keep their requested basenames, exposing wrong locks.
        "ssh": r'''command_text="${2//\/run\/acx-gpu/$REMOTE_ROOT}"
exec bash -c "$command_text"''',
        "sudo": '''if [[ "$1" == test && -n "$LEASE_STATUS" ]]; then
    exit "$LEASE_STATUS"
fi
exec "$@"''',
        "pgrep": '''if [[ "$CANCEL_STOP" == 1 ]]; then
    kill -TERM "$STOP_PID"
fi
if mkdir "$REMOTE_ROOT/activity.lock" 2>/dev/null; then
    printf active > "$RACED_ACTIVITY_LOG"
    rmdir "$REMOTE_ROOT/activity.lock"
fi
exit "$PROCESS_STATUS"''',
        "oci": '''printf called > "$OCI_CALL_LOG"
test -d "$REMOTE_ROOT/activity.lock"
test ! -e "$RACED_ACTIVITY_LOG"''',
    }
    for name, body in scripts.items():
        path = fake_bin / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body + "\n")
        path.chmod(0o700)
    env = dict(
        os.environ,
        PATH=f"{fake_bin}:{os.environ['PATH']}",
        REMOTE_ROOT=str(remote),
        PROCESS_STATUS=str(process_status),
        CANCEL_STOP=str(int(cancel)),
        LEASE_STATUS="" if lease_status is None else str(lease_status),
        OCI_CALL_LOG=str(tmp_path / "oci-called"),
        RACED_ACTIVITY_LOG=str(tmp_path / "raced-activity"),
    )
    return subprocess.run(
        ["bash"], input="export STOP_PID=$$\n" + block, cwd=tmp_path, env=env, text=True, capture_output=True, timeout=8
    )


def test_runbook_stop_guard_prevents_oci_stop_during_active_evaluation(tmp_path: Path) -> None:
    result = run_stop_block(tmp_path, process_status=0)
    assert result.returncode != 0
    assert "bake/evaluation process is active" in result.stderr
    assert not (tmp_path / "oci-called").exists()
    assert not (tmp_path / "remote/activity.lock").exists()


def test_runbook_stop_guard_holds_shared_lock_across_guard_and_stop(tmp_path: Path) -> None:
    result = run_stop_block(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "oci-called").exists()
    assert not (tmp_path / "raced-activity").exists()
    assert not (tmp_path / "remote/activity.lock").exists()


@pytest.mark.parametrize("status", [2, 127])
def test_runbook_stop_guard_fails_closed_on_process_inspection_error(tmp_path: Path, status: int) -> None:
    result = run_stop_block(tmp_path, process_status=status)
    assert result.returncode != 0
    assert "process inspection failed" in result.stderr
    assert not (tmp_path / "oci-called").exists()


def test_runbook_stop_guard_exits_on_signal_and_releases_lock(tmp_path: Path) -> None:
    result = run_stop_block(tmp_path, cancel=True)
    assert result.returncode == 130, result.stderr
    assert not (tmp_path / "oci-called").exists()
    assert not (tmp_path / "remote/activity.lock").exists()


@pytest.mark.parametrize("lease", ["bake.lease", "evaluation.lease"])
def test_runbook_stop_guard_rejects_activity_lease(tmp_path: Path, lease: str) -> None:
    result = run_stop_block(tmp_path, lease=lease)
    assert result.returncode != 0
    assert "active activity lease" in result.stderr
    assert not (tmp_path / "oci-called").exists()


def test_runbook_stop_guard_rejects_occupied_mutex(tmp_path: Path) -> None:
    result = run_stop_block(tmp_path, occupied=True)
    assert result.returncode != 0
    assert not (tmp_path / "oci-called").exists()
    assert (tmp_path / "remote/activity.lock").is_dir()


@pytest.mark.parametrize("status", [1, 2, 127])
def test_runbook_stop_guard_fails_closed_on_lease_inspection_error(tmp_path: Path, status: int) -> None:
    result = run_stop_block(tmp_path, lease="bake.lease", lease_status=status)
    assert result.returncode != 0
    assert "lease inspection failed" in result.stderr
    assert not (tmp_path / "oci-called").exists()
    assert not (tmp_path / "remote/activity.lock").exists()


@pytest.mark.parametrize("envelope", ["", '"'])
def test_live_gpu_verifier_accepts_only_a_fresh_pinned_gpu_result(tmp_path: Path, envelope: str) -> None:
    result = run_live_gpu_verifier(tmp_path, wordpress_config_extra=envelope + wordpress_config() + envelope)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "OK: uncached live GPU inference passed\n"
    requests = (tmp_path / "curl.log").read_text(encoding="utf-8").splitlines()
    assert requests == [
        "https://api.altcontext.com/scene/describe/run",
        ("https://api.altcontext.com/scene/describe/run/123e4567-e89b-42d3-a456-426614174999"),
        "https://api.altcontext.com/scene/describe/run/123e4567-e89b-42d3-a456-426614174999/items",
    ]


def test_live_gpu_verifier_consecutive_requests_have_unique_image_hashes(tmp_path: Path) -> None:
    hashes = []
    for invocation in ("first", "second"):
        request_dir = tmp_path / invocation
        request_dir.mkdir()
        result = run_live_gpu_verifier(request_dir)
        assert result.returncode == 0, result.stderr
        image = (request_dir / "smoke.png").read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        hashes.append(hashlib.sha256(image).hexdigest())
    assert hashes[0] != hashes[1], "Repeated smoke images hit the description cache"


def test_live_gpu_verifier_queues_work_before_polling_for_gpu_start(tmp_path: Path) -> None:
    result = run_live_gpu_verifier(tmp_path)

    assert result.returncode == 0, result.stderr
    verifier = VERIFY_LIVE_GPU.read_text(encoding="utf-8")
    assert "/scene/describe/run" in verifier
    assert "/scene/describe/run/" in verifier
    assert "/scene/describe/multipart" not in verifier


def test_live_gpu_verifier_does_not_use_commented_recognition_key(tmp_path: Path) -> None:
    config = (
        "define('ACX_RECOGNITION_URL','https://api.altcontext.com'); "
        "/* define('ACX_RECOGNITION_API_KEY','commented-key'); */ "
        "define('ACX_RECOGNITION_TENANT_ID','123e4567-e89b-42d3-a456-426614174000');"
    )

    result = run_live_gpu_verifier(tmp_path, wordpress_config_extra=config)

    assert result.returncode != 0
    assert "api_key is missing" in result.stderr
    assert "commented-key" not in result.stdout + result.stderr


def test_live_gpu_verifier_uses_monotonic_deadline_despite_backward_wall_clock(tmp_path: Path) -> None:
    result = run_live_gpu_verifier(
        tmp_path,
        poll_response={
            "run_id": "123e4567-e89b-42d3-a456-426614174999",
            "status": "pending",
        },
        timeout_seconds=1,
        clock_step_seconds=-500,
    )

    assert result.returncode != 0
    assert "did not finish within 1 seconds" in result.stderr
    requests = (tmp_path / "curl.log").read_text(encoding="utf-8").splitlines()
    assert len([request for request in requests if "/scene/describe/run/" in request]) <= 1


def test_live_gpu_verifier_keeps_credentials_out_of_curl_argv(tmp_path: Path) -> None:
    secret = "argv-visible-secret-probe"
    result = run_live_gpu_verifier(tmp_path, wordpress_config_extra=wordpress_config(api_key=secret))

    assert result.returncode == 0, result.stderr
    curl_argv = (tmp_path / "curl-argv.log").read_bytes()
    assert secret.encode() not in curl_argv
    assert b"X-API-Key:" not in curl_argv
    assert b"--config" in curl_argv


def test_live_gpu_verifier_uses_bsd_compatible_mktemp_templates(tmp_path: Path) -> None:
    result = run_live_gpu_verifier(tmp_path, enforce_bsd_mktemp=True)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"adapter": "local_cpu"}, "adapter is not gpu"),
        ({"tier": "provisional_cpu"}, "tier is not final_gpu"),
        ({"cached": True}, "no fresh inference was proved"),
        ({"model_id": "wrong-model"}, "model_id is not the pinned Qwen profile"),
        ({"model_version": "wrong-version"}, "model_version is not Q4_K_M"),
        ({"prompt_or_task_version": "old"}, "prompt version is not 3"),
        ({"alt_text_draft": ""}, "no generated alt_text_draft"),
    ],
)
def test_live_gpu_verifier_fails_closed_on_unproved_response(
    tmp_path: Path, overrides: dict[str, object], expected_error: str
) -> None:
    result = run_live_gpu_verifier(tmp_path, payload=live_gpu_payload(**overrides))

    assert result.returncode != 0
    assert expected_error in result.stderr


def test_live_gpu_verifier_fails_when_live_request_is_unreachable(tmp_path: Path) -> None:
    result = run_live_gpu_verifier(tmp_path, curl_status=7)

    assert result.returncode != 0
    assert "fake-tenant-key-for-preflight-tests" not in result.stdout + result.stderr


def test_15_deploy_shell_surface_remains_bash_3_2_compatible() -> None:
    forbidden = {
        "mapfile/readarray": re.compile(r"(?m)(?:^|[ \t])(mapfile|readarray)(?:[ \t]|$)"),
        "associative arrays": re.compile(r"(?m)(?:^|[ \t])declare[ \t]+-A(?:[ \t]|$)"),
        "case conversion": re.compile(r"\$\{[^}\n]+(?:,,|\^\^)[^}\n]*\}"),
        "combined pipe": re.compile(r"\|&"),
    }
    violations: list[str] = []
    for shell_file in sorted((ROOT / "scripts/deploy").rglob("*.sh")):
        text = shell_file.read_text(encoding="utf-8")
        for feature, pattern in forbidden.items():
            if pattern.search(text):
                violations.append(f"{shell_file.relative_to(ROOT)}: {feature}")

    assert violations == []


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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("WORDPRESS_CONFIG_EXTRA", "'" + wordpress_config() + "'"),
        ("ACX_GPU_ENDPOINT_API_KEY", '"unterminated-fake-key'),
        ("ACX_GPU_ENDPOINT_API_KEY", "'unterminated-fake-key"),
        ("ACX_GPU_ENDPOINT_API_KEY", '"fake"trailing"'),
        ("ACX_GPU_ENDPOINT_API_KEY", '"fake\\nkey"'),
    ],
)
def test_preflight_rejects_ambiguous_dotenv_quotes(tmp_path: Path, key: str, value: str) -> None:
    producer = valid_env()
    producer[key] = value
    result = run_preflight(tmp_path, producer=producer)
    assert result.returncode != 0
    assert "dotenv" in result.stderr
    assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("envelope", ["", '"', "'"])
def test_accepted_dotenv_values_match_compose(tmp_path: Path, envelope: str) -> None:
    if not shutil.which("docker"):
        pytest.skip("Docker Compose is required for dotenv parity")
    version = subprocess.run(["docker", "compose", "version"], capture_output=True)
    if version.returncode:
        pytest.skip("Docker Compose is required for dotenv parity")
    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_API_KEY"] = envelope + "fake-gpu-key" + envelope
    producer["WORDPRESS_CONFIG_EXTRA"] = '"' + wordpress_config() + '"'
    result = run_preflight(tmp_path, producer=producer)
    assert result.returncode == 0, result.stderr
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services:\n  smoke:\n    image: scratch\n    env_file: producer.env\n")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(tmp_path / "producer.env"),
            "-f",
            str(compose_file),
            "config",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    deployed = json.loads(result.stdout)["services"]["smoke"]["environment"]
    assert deployed["ACX_GPU_ENDPOINT_API_KEY"] == "fake-gpu-key"
    assert deployed["WORDPRESS_CONFIG_EXTRA"] == wordpress_config()


@pytest.mark.parametrize("value", ["'" + wordpress_config() + "'", '"unterminated-fake-key'])
def test_compose_and_preflight_reject_malformed_dotenv(tmp_path: Path, value: str) -> None:
    if not shutil.which("docker") or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose is required for dotenv parity")
    producer = valid_env()
    key = "WORDPRESS_CONFIG_EXTRA" if value.startswith("'define") else "ACX_GPU_ENDPOINT_API_KEY"
    producer[key] = value
    result = run_preflight(tmp_path, producer=producer)
    assert result.returncode != 0
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services:\n  smoke:\n    image: scratch\n    env_file: producer.env\n")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(tmp_path / "producer.env"),
            "-f",
            str(compose_file),
            "config",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "load_options",
    [
        "",
        "--load-dir relative",
        "--load-dir /run/acx",
        "--load-dir /run/acx-write --fence-delay-seconds nan",
        "--load-dir /run/acx-write --fence-delay-seconds -1",
        "--load-dir /run/acx-write --load-stale-grace-seconds nan",
        "--load-dir /run/acx-write --load-stale-grace-seconds 1",
    ],
)
def test_reaper_requires_runnable_production_load_source(tmp_path: Path, load_options: str) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    command = (
        "/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap "
        "--instance-id ${GPU_INSTANCE_ID} --max-lease-seconds ${MAX_LEASE_SECONDS} " + load_options
    )
    result = run_preflight(
        tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(reaper_env, exec_start=command)
    )
    assert result.returncode != 0
    assert "structurally valid GPU lifecycle reaper" in result.stderr
    assert "MANUAL STOP" not in result.stdout


def test_sync_demo_missing_contract_fails_before_remote_mutation(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_log = tmp_path / "remote-called"
    for name in ("ssh", "scp"):
        stub = fake_bin / name
        stub.write_text('#!/bin/sh\nprintf called >> "$REMOTE_CALL_LOG"\nexit 99\n')
        stub.chmod(0o700)
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", REMOTE_CALL_LOG=str(remote_log),
               GPU_ENV_CONTRACT_SRC=str(tmp_path / "missing-contract.sh"), OCI_HOST="fake.invalid")
    result = subprocess.run(["bash", str(SYNC_DEMO)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=8)
    assert result.returncode == 2, result.stderr
    assert "source file not found" in result.stderr
    assert not remote_log.exists()


def test_bootstrap_missing_staged_contract_fails_before_mutation(tmp_path: Path) -> None:
    # Reproduce the deployment transfer phase using its actual source list.
    # No manual runbook helper copy: that previously hid the missing SCP.
    staged = tmp_path / "demo"
    staged.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "ssh").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "scp").write_text("""#!/usr/bin/env bash
set -eu
destination="${2#*:}"
case "$destination" in
  /opt/acx-backend/demo/*)
    destination="$STAGED_DEMO/${destination#/opt/acx-backend/demo/}"
    mkdir -p "$(dirname "$destination")"
    cp "$1" "$destination" ;;
  *) exit 2 ;;
esac
""")
    for executable in fake_bin.iterdir():
        executable.chmod(0o700)
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", STAGED_DEMO=str(staged), OCI_HOST="fake.invalid")
    transfer = SYNC_DEMO.read_text().split("seed_media_files=()", 1)[0]
    transfer = transfer.replace('$(dirname "${BASH_SOURCE[0]}")', str(SYNC_DEMO.parent))
    result = subprocess.run(["bash"], input=transfer, cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (staged / "lib/gpu-env-contract.sh").read_bytes() == CONTRACT.read_bytes()
    # Even after the sibling transfer fix lands, exercise the fail-fast guard.
    (staged / "lib/gpu-env-contract.sh").unlink(missing_ok=True)
    result = subprocess.run(
        ["bash", str(staged / "bootstrap-wp.sh")], env=dict(env, DEMO_DIR=str(staged)), text=True, capture_output=True
    )
    assert result.returncode == 2
    assert "missing staged lib/gpu-env-contract.sh" in result.stderr
    assert not (staged / ".env").exists()
    assert "Installing" not in result.stdout


def test_verifier_request_waits_for_stopped_gpu_through_real_run_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import tempfile
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from urllib.parse import urlsplit

    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    import httpx
    from fastapi import BackgroundTasks
    from starlette.datastructures import FormData, Headers, UploadFile

    import scene.application.describe_run_worker as worker
    import scene.interface_adapters.http.routers.describe_run as route
    from scene.domain.description import DescriptionAdapterKind, DescriptionResultTier

    # Replay the shell-generated multipart fields through the real route and
    # worker. Only persistence, external health and inference use fakes.
    result = run_live_gpu_verifier(tmp_path)
    assert result.returncode == 0, result.stderr
    argv = (tmp_path / "curl-argv.log").read_bytes().decode().split("\0")
    data = dict(argv[i + 1].split("=", 1) for i, arg in enumerate(argv) if arg == "--form-string")
    image_field = next(argv[i + 1].split("=", 1)[0] for i, arg in enumerate(argv) if arg == "-F")
    paths = [urlsplit(url).path.removeprefix("/scene") for url in (tmp_path / "curl.log").read_text().splitlines()]
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://localhost:8000")
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "2")
    monkeypatch.setattr(worker, "_GPU_HEALTH_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(route, "get_description_adapter", lambda: SimpleNamespace(kind=DescriptionAdapterKind.GPU))
    events = []
    run = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(data["tenant_id"]),
        status="pending",
        run_kind="bulk",
        phase="queued",
        completed_items=0,
        failed_items=0,
        skipped_items=0,
        total_items=1,
        cancel_requested=False,
        recognition_enabled=False,
    )
    item = SimpleNamespace(
        media_id=json.loads(data["media_ids"])[0],
        image_bytes=b"fake-image",
        image_content_type="image/png",
        status="queued",
        alt_text_draft=None,
        caption=None,
        provenance=None,
        tier=None,
        result_generation=0,
    )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def commit(self):
            pass

    class Repository:
        def __init__(self, session):
            pass

        async def create_run(self, **kwargs):
            assert kwargs["images"][item.media_id] == (b"fake-image", "image/png")
            assert kwargs["recognition_enabled"] is False
            return run.id

        async def get_run(self, **kwargs):
            return run

        async def list_run_items(self, **kwargs):
            return [item]

        async def mark_item(self, **kwargs):
            item.status = kwargs["status"]
            if item.status == "completed":
                run.status = "completed"
                run.completed_items = 1

        async def record_item_result(self, **kwargs):
            for key in ("alt_text_draft", "caption", "provenance", "tier"):
                setattr(item, key, kwargs.get(key))

        async def mark_run_failed(self, **kwargs):
            run.status = "failed"

    async def publish_load(*args):
        events.append("load")

    for module in (worker, route):
        monkeypatch.setattr(module, "DescribeRunRepository", Repository)
        monkeypatch.setattr(module, "set_tenant_context", AsyncMock())
        monkeypatch.setattr(module, "dump_load_snapshot", publish_load)
    monkeypatch.setattr(
        worker, "get_tenant_record", AsyncMock(return_value=SimpleNamespace(naming_agreement_enabled=False))
    )
    monkeypatch.setattr(route, "require_tenant_record", AsyncMock())
    monkeypatch.setattr(route, "maybe_consume_demo_quota", AsyncMock())
    monkeypatch.setattr(route, "worker_session_factory", lambda session: Session)

    def health(request):
        assert events[0] == "load", "load must be published before warmup"
        events.append("health")
        count = events.count("health")
        if count == 1:
            raise httpx.ConnectError("stopped", request=request)
        return httpx.Response(503 if count == 2 else 200, request=request)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        worker.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(health), **kw)
    )

    async def describe_one(*args, **kwargs):
        assert events == ["load", "health", "health", "health"], "inference ran before readiness"
        events.append("inference")
        payload = live_gpu_payload()
        return worker.DescribeItemOutcome(
            alt_text_draft=payload.pop("alt_text_draft"),
            caption="gradient",
            provenance=payload,
            tier=DescriptionResultTier.FINAL_GPU,
        )

    monkeypatch.setattr(route, "_build_describe_one", lambda **kwargs: describe_one)
    with tempfile.SpooledTemporaryFile() as image:
        image.write(b"fake-image")
        image.seek(0)
        form = FormData(
            [
                *data.items(),
                (
                    image_field,
                    UploadFile(image, filename="smoke.png", headers=Headers({"content-type": "image/png"})),
                ),
            ]
        )
        auth = SimpleNamespace(tenant_claim=data["tenant_id"], user_id=42)

        async def exercise():
            endpoint = next(r.endpoint for r in route.router.routes if r.path == paths[0] and "POST" in r.methods)
            background = BackgroundTasks()
            response = await endpoint(
                request=SimpleNamespace(form=AsyncMock(return_value=form)),
                background_tasks=background,
                auth=auth,
                session=Session(),
            )
            assert response.run_id == str(run.id)
            await asyncio.wait_for(background(), timeout=3)
            for path in paths[1:]:
                endpoint = next(
                    r.endpoint for r in route.router.routes if "GET" in r.methods and r.path_regex.match(path)
                )
                response = await endpoint(run_id=run.id, auth=auth, session=Session())
                if path.endswith("/items"):
                    assert response.items[0].status == "completed"
                    assert response.items[0].tier == "final_gpu"
                    assert response.items[0].provenance["cached"] is False
                else:
                    assert response.status == "completed"
                    assert response.completed == 1

        async def bounded_exercise():
            await asyncio.wait_for(exercise(), timeout=5)

        asyncio.run(bounded_exercise())
    assert events == ["load", "health", "health", "health", "inference", "load"]


@pytest.mark.parametrize("unset", ["MAX_LEASE_SECONDS", "GPU_INSTANCE_ID", "MAX_LEASE_SECONDS=3600"])
def test_11_rejects_unset_required_reaper_environment(tmp_path: Path, unset: str) -> None:
    env_file = tmp_path / "reaper.env"
    env_file.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(
        env_file, unset_environment=unset,
    ))
    assert result.returncode != 0
    assert "UnsetEnvironment" in result.stderr
    assert "MANUAL STOP" not in result.stdout


def test_11_rejects_unrelated_timer_target(tmp_path: Path) -> None:
    env_file = tmp_path / "reaper.env"
    env_file.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(
        env_file, timer_target="unrelated.service",
    ))
    assert result.returncode != 0
    assert "must activate acx-gpu-reap.service" in result.stderr
    assert "MANUAL STOP" not in result.stdout


@pytest.mark.parametrize("optional", [True, False])
def test_11_environment_file_optional_metadata(tmp_path: Path, optional: bool) -> None:
    env_file = tmp_path / "reaper.env"
    env_file.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    files = f"{env_file} (ignore_errors=no) {tmp_path / 'absent.env'} (ignore_errors={'yes' if optional else 'no'})"
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=reaper_systemctl_script(
        env_file, environment_files=files,
    ))
    assert (result.returncode == 0) == optional, result.stderr
    assert ("MANUAL STOP" in result.stdout) == optional


@pytest.mark.parametrize("kind", ["missing", "non-executable", "non-oci", "true", "valid"])
def test_11_reaper_oci_executable(tmp_path: Path, kind: str) -> None:
    reaper_env = tmp_path / "gpu-lifecycle.env"
    reaper_env.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    unit = reaper_systemctl_script(reaper_env)
    binary = tmp_path / "candidate"
    if kind != "missing":
        binary.write_text("#!/bin/sh\n" + (
            '[ "$1" = --help ] || exit 9\necho "Oracle Cloud Infrastructure CLI"\n'
            if kind in ("valid", "non-executable") else "echo unrelated-tool\n"
        ))
        binary.chmod(0o644 if kind == "non-executable" else 0o755)
    unit = unit.replace(str(tmp_path / "oci-stub"), "/bin/true" if kind == "true" else str(binary))
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    if kind == "valid":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "OCI executable must run as the service user" in result.stderr
        assert "MANUAL STOP" not in result.stdout


def test_11_reaper_rejects_inaccessible_lease_path(tmp_path: Path) -> None:
    env_file = tmp_path / "reaper.env"
    env_file.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    unit = reaper_systemctl_script(env_file)
    unit = unit.replace(str(tmp_path / "running-since.json"), "/proc/acx-review/running-since.json")
    result = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    assert result.returncode != 0
    assert "lease" in result.stderr


def test_live_gpu_verifier_accepts_unterminated_env(tmp_path: Path) -> None:
    result = run_live_gpu_verifier(tmp_path, final_newline=False)
    assert result.returncode == 0, result.stderr


def test_11_reaper_checks_lease_directory_writes_without_changing_state(tmp_path: Path) -> None:
    env_file = tmp_path / "reaper.env"
    env_file.write_text("GPU_INSTANCE_ID=ocid1.instance.oc1.iad.fakeinstance\nMAX_LEASE_SECONDS=3600\n")
    unit = reaper_systemctl_script(env_file)
    directory = tmp_path / "leases"
    directory.mkdir()
    lease = directory / "running-since.json"
    lease.write_text('{"existing": "lease must survive preflight"}\n')
    original = lease.read_bytes()
    unit = unit.replace(str(tmp_path / "running-since.json"), str(lease))
    control = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
    assert control.returncode == 0, control.stderr
    assert lease.read_bytes() == original
    assert list(directory.iterdir()) == [lease]
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory mode restrictions")
    directory.chmod(0o500)
    try:
        result = run_preflight(tmp_path, check_reaper=True, systemctl_script=unit)
        assert result.returncode != 0
        assert "lease" in result.stderr
        assert lease.read_bytes() == original
    finally:
        directory.chmod(0o700)


@pytest.mark.parametrize("escalate", [False, True])
@pytest.mark.parametrize("system_imports", [False, True])
def test_11_lease_probe_interpreter_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, escalate: bool, system_imports: bool,
) -> None:
    """Intercept absolute system executables without changing the host or using sudo."""
    import io
    import shlex
    from types import SimpleNamespace

    system_python = tmp_path / "system-python3"
    system_python.write_text(
        "#!/bin/sh\n" + (
            f"exec {shlex.quote(sys.executable)} \"$@\"\n" if system_imports
            else "echo 3.9.6\necho 'ImportError: datetime.UTC' >&2\nexit 1\n"
        )
    )
    system_python.chmod(0o755)
    env_file = tmp_path / "reaper.env"
    unit = reaper_systemctl_script(env_file)
    exec_start = next(line.removeprefix("ExecStart=") for line in unit.splitlines() if line.startswith("ExecStart="))
    monkeypatch.setattr(sys, "argv", [
        "-c", exec_start, str(ROOT), "ocid1.instance.oc1.iad.fakeinstance",
        "3600", "600", "60", "probe-user",
    ])
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(
        pw_uid=os.geteuid() + int(escalate), pw_name=name, pw_dir=str(tmp_path),
    ))
    diagnostics = io.StringIO()
    monkeypatch.setattr(os, "fdopen", lambda *args: diagnostics)
    original_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "/usr/bin/sudo":
            assert escalate
            command = command[command.index("-i") + 1:]
            command = command[3:]  # HOME, PATH and LC_ALL
        if command[0] == "/usr/bin/python3":
            command = [str(system_python), *command[1:]]
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    program = SCRIPT.read_text().split("reaper_execstart_is_structural() {\n    python3 -c '\n", 1)[1].split("\n' \"$@\" 3>&2", 1)[0]
    status = 0
    try:
        exec(compile(program, str(SCRIPT), "exec"), {})
    except SystemExit as error:
        status = error.code
    assert status == (1 if not system_imports else 0), diagnostics.getvalue()
    if not system_imports:
        assert "probe interpreter /usr/bin/python3 (version 3.9.6)" in diagnostics.getvalue()
        assert "cannot import" in diagnostics.getvalue()
        assert "lease path" not in diagnostics.getvalue()
    if not escalate:
        assert any(command[0] == "/usr/bin/python3" for command in calls)
    assert not list(tmp_path.glob(".acx-lease-preflight-*"))


@pytest.mark.parametrize("quote", ["'", '"'])
@pytest.mark.parametrize("role", ["producer", "demo"])
def test_unrelated_multiline_value_cannot_hide_adapter(tmp_path: Path, quote: str, role: str) -> None:
    values = valid_env() if role == "producer" else valid_demo_env()
    values.pop("ACX_DESCRIPTION_ADAPTER")
    document = "OTHER=" + quote + "\nACX_DESCRIPTION_ADAPTER=gpu_qwen30b\n" + quote + "\n" + env_text(values)
    result = run_preflight(tmp_path, **{role + "_text": document})
    assert result.returncode != 0
    assert "multiline" in result.stderr


@pytest.mark.parametrize("quote", ["'", '"'])
def test_multiline_adapter_assignment_matches_compose(tmp_path: Path, quote: str) -> None:
    if not shutil.which("docker") or subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose is required for dotenv parity")
    values = valid_env()
    values.pop("ACX_DESCRIPTION_ADAPTER")
    values["WORDPRESS_CONFIG_EXTRA"] = '"' + wordpress_config() + '"'
    document = "OTHER=" + quote + "\nACX_DESCRIPTION_ADAPTER=gpu_qwen30b\n" + quote + "\n" + env_text(values)
    preflight = run_preflight(tmp_path, producer_text=document)
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services:\n  smoke:\n    image: scratch\n    env_file: producer.env\n")
    result = subprocess.run(
        ["docker", "compose", "--env-file", str(tmp_path / "producer.env"),
         "-f", str(compose_file), "config", "--format", "json"],
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    deployed = json.loads(result.stdout)["services"]["smoke"]["environment"]
    assert "ACX_DESCRIPTION_ADAPTER" not in deployed
    assert "ACX_DESCRIPTION_ADAPTER=gpu_qwen30b" in deployed["OTHER"]
    assert preflight.returncode != 0
