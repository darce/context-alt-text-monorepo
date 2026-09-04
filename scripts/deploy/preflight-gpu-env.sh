#!/usr/bin/env bash
# Validate the complete demo-to-description-service GPU flip before deployment.
# Docker Compose env files are data, not shell; never source the input file.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/gpu-env-contract.sh
source "${script_dir}/lib/gpu-env-contract.sh"

if [[ $# -ne 1 ]]; then
    echo "Usage: scripts/deploy/preflight-gpu-env.sh <env-file>" >&2
    exit 2
fi

env_file="$1"
if [[ ! -r "$env_file" || ! -f "$env_file" ]]; then
    echo "ERROR [0] env file must be a readable regular file. Pass its path as the only argument." >&2
    exit 2
fi

# Return the first exact KEY= entry without executing substitutions, commands,
# quotes, or semicolons in a Compose dotenv value.
env_get() {
    local key="$1"
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        case "$line" in
            "${key}="*)
                line="${line#*=}"
                if [[ ${#line} -ge 2 ]]; then
                    case "$line" in
                        \"*\") line="${line:1:${#line}-2}" ;;
                        \'*\') line="${line:1:${#line}-2}" ;;
                    esac
                fi
                printf '%s' "$line"
                return 0
                ;;
        esac
    done < "$env_file"
    return 0
}

# Read the WordPress constants when the demo env keeps them in its one
# operative WORDPRESS_CONFIG_EXTRA value. Names are fixed by this script.
php_define_value() {
    local name="$1"
    local source_value="$2"
    printf '%s' "$source_value" \
        | tr ';' '\n' \
        | sed -n "s/.*define(['\"]${name}['\"],[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" \
        | sed -n '1p'
}

adapter="$(env_get ACX_DESCRIPTION_ADAPTER)"
endpoint_url="$(env_get ACX_GPU_ENDPOINT_URL)"
endpoint_api_key="$(env_get ACX_GPU_ENDPOINT_API_KEY)"
snapshot_dir="$(env_get ACX_GPU_SNAPSHOT_DIR)"
state_path="$(env_get ACX_GPU_STATE_PATH)"
stale_seconds="$(env_get ACX_GPU_STATE_STALE_SECONDS)"

if ! acx_is_trusted_describe_profile "$adapter"; then
    echo "ERROR [1] ACX_DESCRIPTION_ADAPTER must be florence_small, gpu_qwen30b, or gpu_qwen30b_ensemble. Set one validated live adapter (redacted length=${#adapter})." >&2
    exit 1
fi

if [[ "$adapter" == gpu_* ]]; then
    case "$endpoint_url" in
        http://?*|https://?*) ;;
        *)
            echo "ERROR [2] ACX_GPU_ENDPOINT_URL must be set to an http:// or https:// URL for a gpu_* adapter. Set the private A10 endpoint (redacted length=${#endpoint_url})." >&2
            exit 1
            ;;
    esac
fi

if [[ -n "$endpoint_url" && -z "$endpoint_api_key" ]]; then
    echo "ERROR [3] ACX_GPU_ENDPOINT_API_KEY is unset while ACX_GPU_ENDPOINT_URL is set. Add the endpoint credential (redacted length=${#endpoint_api_key})." >&2
    exit 1
fi

normalized_snapshot_dir="${snapshot_dir%/}"
[[ -n "$normalized_snapshot_dir" ]] || normalized_snapshot_dir="/"
state_dir=""
if [[ "$state_path" == */* ]]; then
    state_dir="${state_path%/*}"
    [[ -n "$state_dir" ]] || state_dir="/"
fi
if [[ -z "$snapshot_dir" || -z "$state_path" || "$normalized_snapshot_dir" != "$state_dir" ]]; then
    echo "ERROR [4] ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH must both be set and name the same directory. Set ACX_GPU_STATE_PATH=<snapshot-dir>/gpu-state.json." >&2
    exit 1
fi

case "$stale_seconds" in
    ''|*[!0-9]*)
        echo "ERROR [5] ACX_GPU_STATE_STALE_SECONDS must be a positive integer. Set the maximum accepted snapshot age in seconds (redacted length=${#stale_seconds})." >&2
        exit 1
        ;;
esac
if [[ -z "${stale_seconds//0/}" ]]; then
    echo "ERROR [5] ACX_GPU_STATE_STALE_SECONDS must be a positive integer. Set the maximum accepted snapshot age in seconds (redacted length=${#stale_seconds})." >&2
    exit 1
fi

recognition_url="$(env_get ACX_RECOGNITION_URL)"
recognition_api_key="$(env_get ACX_RECOGNITION_API_KEY)"
recognition_tenant_id="$(env_get ACX_RECOGNITION_TENANT_ID)"
wordpress_config_extra="$(env_get WORDPRESS_CONFIG_EXTRA)"
if [[ -n "$wordpress_config_extra" ]]; then
    [[ -n "$recognition_url" ]] || recognition_url="$(php_define_value ACX_RECOGNITION_URL "$wordpress_config_extra")"
    [[ -n "$recognition_api_key" ]] || recognition_api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$wordpress_config_extra")"
    [[ -n "$recognition_tenant_id" ]] || recognition_tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$wordpress_config_extra")"
fi

missing_recognition=()
[[ -n "$recognition_url" ]] || missing_recognition+=("ACX_RECOGNITION_URL")
[[ -n "$recognition_api_key" ]] || missing_recognition+=("ACX_RECOGNITION_API_KEY")
[[ -n "$recognition_tenant_id" ]] || missing_recognition+=("ACX_RECOGNITION_TENANT_ID")
if (( ${#missing_recognition[@]} > 0 )); then
    printf 'ERROR [6] demo recognition config is incomplete. Set these keys (directly or as WORDPRESS_CONFIG_EXTRA defines):' >&2
    printf ' %s' "${missing_recognition[@]}" >&2
    printf '. Secret values remain redacted; ACX_RECOGNITION_API_KEY length=%s.\n' "${#recognition_api_key}" >&2
    exit 1
fi

printf 'OK: GPU env preflight passed (adapter=%s).\n' "$adapter"
