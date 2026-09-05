#!/usr/bin/env bash
# Prove the configured description service performs one fresh GPU inference.
# The demo env supplies the service URL and tenant credential already used by
# WordPress; the credential is never printed.

set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" || ! -r "$1" ]]; then
    echo "Usage: verify-live-gpu.sh <demo-env-file>" >&2
    exit 2
fi

demo_env="$1"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=gpu-env-contract.sh
source "${script_dir}/gpu-env-contract.sh"

wordpress_config_lines=()
while IFS= read -r line; do
    wordpress_config_lines+=("$line")
done < <(sed -n 's/^WORDPRESS_CONFIG_EXTRA=//p' "$demo_env")
if [[ ${#wordpress_config_lines[@]} -ne 1 ]]; then
    echo "ERROR: demo env must contain exactly one canonical WORDPRESS_CONFIG_EXTRA assignment." >&2
    exit 1
fi
wordpress_config_extra="${wordpress_config_lines[0]}"
base_url="$(php_define_value ACX_RECOGNITION_URL "$wordpress_config_extra")"
api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$wordpress_config_extra")"
tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$wordpress_config_extra")"
for required_name in base_url api_key tenant_id; do
    if [[ -z "${!required_name}" ]]; then
        echo "ERROR: ${required_name} is missing from WORDPRESS_CONFIG_EXTRA; values remain redacted." >&2
        exit 1
    fi
done

smoke_image="$(mktemp /tmp/acx-gpu-smoke.XXXXXX)"
response_file="$(mktemp /tmp/acx-gpu-response.XXXXXX)"
curl_config="$(mktemp /tmp/acx-gpu-curl.XXXXXX)"
trap 'rm -f "$smoke_image" "$response_file" "$curl_config"' EXIT
chmod 600 "$curl_config"
printf '%s\0%s\0' "$api_key" "$tenant_id" | python3 -c '
import sys

values = sys.stdin.buffer.read().split(b"\0")
if len(values) != 3 or values[-1] or any(b"\r" in value or b"\n" in value for value in values[:2]):
    raise SystemExit("live GPU smoke failed: credential contains an invalid control character")

def curl_quote(value):
    return value.decode("utf-8").replace("\\", "\\\\").replace("\"", "\\\"")

with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"header = \"X-API-Key: {curl_quote(values[0])}\"\n")
    handle.write(f"header = \"X-Tenant-ID: {curl_quote(values[1])}\"\n")
' "$curl_config"
python3 - "$smoke_image" <<'PY'
import struct
import sys
import zlib

width = height = 64
rows = b"".join(
    b"\0" + b"".join(bytes((x * 4, y * 4, 96)) for x in range(width))
    for y in range(height)
)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(rows))
png += chunk(b"IEND", b"")
with open(sys.argv[1], "wb") as handle:
    handle.write(png)
PY

# A random media id makes an existing cache row overwhelmingly unlikely. The
# asynchronous route durably queues work, which publishes describe load for the
# start timer before the worker waits for GPU readiness. The response must still
# report cached=false, so a collision fails closed.
media_id="$(python3 -c 'import secrets; print(secrets.randbelow(2_000_000_000) + 1)')"
request_json="$(printf '{\"tenant_id\":\"%s\",\"media_id\":%s,\"tier\":\"gpu\",\"context\":{\"filename\":\"gpu-flip-smoke.png\"}}' "$tenant_id" "$media_id")"
curl --fail-with-body --silent --show-error --max-time 30 \
    --config "$curl_config" \
    -F "request=${request_json};type=application/json" \
    -F "image_${media_id}=@${smoke_image};type=image/png" \
    --output "$response_file" \
    "${base_url%/}/scene/describe/async"

job_id="$(python3 - "$response_file" <<'PY'
import json
import sys
import uuid

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
try:
    job_id = str(uuid.UUID(payload.get("job_id", "")))
except (AttributeError, TypeError, ValueError):
    raise SystemExit("live GPU smoke failed: async enqueue returned no valid job_id") from None
if payload.get("status") not in {"queued", "running", "provisional", "final"}:
    raise SystemExit("live GPU smoke failed: async enqueue did not accept the job")
print(job_id)
PY
)"

readonly LIVE_GPU_POLL_TIMEOUT_SECONDS="${LIVE_GPU_POLL_TIMEOUT_SECONDS:-900}"
case "$LIVE_GPU_POLL_TIMEOUT_SECONDS" in
    ''|*[!0-9]*|0)
        echo "live GPU smoke failed: LIVE_GPU_POLL_TIMEOUT_SECONDS must be a positive integer" >&2
        exit 2
        ;;
esac
monotonic_seconds() {
    python3 -c 'import time; print(int(time.monotonic()))'
}
poll_deadline=$(( $(monotonic_seconds) + LIVE_GPU_POLL_TIMEOUT_SECONDS ))
poll_complete=0
while :; do
    poll_now="$(monotonic_seconds)"
    poll_remaining=$(( poll_deadline - poll_now ))
    (( poll_remaining > 0 )) || break
    request_timeout=30
    (( poll_remaining < request_timeout )) && request_timeout="$poll_remaining"
    curl --fail-with-body --silent --show-error --max-time "$request_timeout" \
        --config "$curl_config" \
        --output "$response_file" \
        "${base_url%/}/scene/describe/jobs/${job_id}"
    if python3 - "$response_file" "$job_id" <<'PY'
import json
import sys

path, expected_job_id = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
if payload.get("job_id") != expected_job_id:
    raise SystemExit("live GPU smoke failed: poll returned a different job_id")
status = payload.get("status")
if status == "final":
    if payload.get("tier") != "final_gpu":
        raise SystemExit("live GPU smoke failed: final job tier is not final_gpu")
    visual_facts = payload.get("visual_facts")
    if not isinstance(visual_facts, dict):
        raise SystemExit("live GPU smoke failed: final job has no visual_facts")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(visual_facts, handle)
    raise SystemExit(0)
if status in {"degraded", "failed"}:
    raise SystemExit(f"live GPU smoke failed: async job ended with status {status}")
if status not in {"queued", "running", "provisional"}:
    raise SystemExit("live GPU smoke failed: async job returned an unknown status")
raise SystemExit(10)
PY
    then
        poll_complete=1
        break
    else
        poll_status=$?
        [[ "$poll_status" -eq 10 ]] || exit "$poll_status"
    fi
    poll_now="$(monotonic_seconds)"
    poll_remaining=$(( poll_deadline - poll_now ))
    (( poll_remaining > 0 )) || break
    sleep_seconds=5
    (( poll_remaining < sleep_seconds )) && sleep_seconds="$poll_remaining"
    sleep "$sleep_seconds"
done
if [[ "$poll_complete" -ne 1 ]]; then
    echo "live GPU smoke failed: async job did not finish within ${LIVE_GPU_POLL_TIMEOUT_SECONDS} seconds" >&2
    exit 1
fi

python3 - "$response_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
if payload.get("adapter") != "gpu":
    raise SystemExit("live GPU smoke failed: response adapter is not gpu")
if payload.get("tier") != "final_gpu":
    raise SystemExit("live GPU smoke failed: response tier is not final_gpu")
if payload.get("cached") is not False:
    raise SystemExit("live GPU smoke failed: response was cached; no fresh inference was proved")
expected_model_id = "unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639"
if payload.get("model_id") != expected_model_id:
    raise SystemExit("live GPU smoke failed: response model_id is not the pinned Qwen profile")
if payload.get("model_version") != "Q4_K_M":
    raise SystemExit("live GPU smoke failed: response model_version is not Q4_K_M")
if payload.get("prompt_or_task_version") != "3":
    raise SystemExit("live GPU smoke failed: response prompt version is not 3")
if not isinstance(payload.get("alt_text_draft"), str) or not payload.get("alt_text_draft").strip():
    raise SystemExit("live GPU smoke failed: response has no generated alt_text_draft")
print("OK: uncached live GPU inference passed")
PY
