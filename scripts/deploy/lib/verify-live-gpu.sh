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
# shellcheck source=describe-gate.sh
source "${script_dir}/describe-gate.sh"

mapfile -t wordpress_config_lines < <(sed -n 's/^WORDPRESS_CONFIG_EXTRA=//p' "$demo_env")
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

smoke_image="$(mktemp /tmp/acx-gpu-smoke.XXXXXX.png)"
response_file="$(mktemp /tmp/acx-gpu-response.XXXXXX.json)"
trap 'rm -f "$smoke_image" "$response_file"' EXIT
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
# response must still report cached=false, so a collision fails closed.
media_id="$(python3 -c 'import secrets; print(secrets.randbelow(2_000_000_000) + 1)')"
request_json="$(printf '{\"tenant_id\":\"%s\",\"media_id\":%s,\"tier\":\"gpu\",\"context\":{\"filename\":\"gpu-flip-smoke.png\"}}' "$tenant_id" "$media_id")"
curl --fail-with-body --silent --show-error --max-time 600 \
    -H "X-API-Key: ${api_key}" \
    -H "X-Tenant-ID: ${tenant_id}" \
    -F "request=${request_json};type=application/json" \
    -F "image_${media_id}=@${smoke_image};type=image/png" \
    --output "$response_file" \
    "${base_url%/}/scene/describe/multipart"

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
