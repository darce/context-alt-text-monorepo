#!/usr/bin/env bash
# Validate the complete producer-to-demo GPU flip before deployment.
# Docker Compose env files are data, not shell; never source either input file.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/gpu-env-contract.sh
source "${script_dir}/lib/gpu-env-contract.sh"

if [[ $# -ne 2 ]]; then
    echo "Usage: scripts/deploy/preflight-gpu-env.sh <producer-env-file> <demo-env-file>" >&2
    exit 2
fi

producer_env="$1"
demo_env="$2"

for env_file in "$producer_env" "$demo_env"; do
    if [[ ! -r "$env_file" || ! -f "$env_file" ]]; then
        echo "ERROR [0] both env files must be readable regular files. Pass producer first, then demo." >&2
        exit 2
    fi
done

relevant_keys=(
    ACX_DESCRIPTION_ADAPTER
    ACX_GPU_ENDPOINT_URL
    ACX_GPU_ENDPOINT_API_KEY
    ACX_GPU_SNAPSHOT_DIR
    ACX_GPU_STATE_PATH
    ACX_GPU_STATE_STALE_SECONDS
    ACX_RECOGNITION_URL
    ACX_RECOGNITION_API_KEY
    ACX_RECOGNITION_TENANT_ID
    RECOGNITION_SECRET_BACKEND
    RECOGNITION_VAULT_SECRET_MAP
    WORDPRESS_CONFIG_EXTRA
)

# Compose uses the final assignment. Reject duplicate contract keys instead of
# letting an earlier safe-looking value conceal the value deployment consumes.
reject_duplicate_keys() {
    local role="$1" file="$2" key line count
    for key in "${relevant_keys[@]}"; do
        count=0
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line%$'\r'}"
            case "$line" in
                "${key}="*) count=$((count + 1)) ;;
            esac
        done < "$file"
        if (( count > 1 )); then
            echo "ERROR [7] ${role} env contains duplicate ${key} assignments. Keep only the final effective assignment before deployment (count=${count})." >&2
            exit 1
        fi
    done
}

reject_duplicate_keys producer "$producer_env"
reject_duplicate_keys demo "$demo_env"

# Return the final exact KEY= entry without evaluating shell syntax.
env_get() {
    local file="$1" key="$2" line value=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%$'\r'}"
        case "$line" in
            "${key}="*)
                value="${line#*=}"
                if [[ ${#value} -ge 2 ]]; then
                    case "$value" in
                        \"*\") value="${value:1:${#value}-2}" ;;
                        \'*\') value="${value:1:${#value}-2}" ;;
                    esac
                fi
                ;;
        esac
    done < "$file"
    printf '%s' "$value"
}

php_define_value() {
    local name="$1" source_value="$2"
    printf '%s' "$source_value" \
        | tr ';' '\n' \
        | sed -n "s/.*define(['\"]${name}['\"],[[:space:]]*['\"]\([^'\"]*\)['\"].*/\1/p" \
        | sed -n '1p'
}

is_placeholder() {
    local lowered
    lowered="$(printf '%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
    case "$lowered" in
        ''|*replace*|*placeholder*|*change-me*|*changeme*|*paste-key*|*paste_secret*|'<'*|'>'*) return 0 ;;
        *) return 1 ;;
    esac
}

is_http_url() {
    printf '%s' "$1" | LC_ALL=C grep -Eq '^https?://[^/[:space:]]+(/[^[:space:]]*)?$'
}

is_tenant_uuid() {
    printf '%s' "$1" | LC_ALL=C grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
}

vault_map_value() {
    local map="$1" key="$2"
    printf '%s' "$map" | sed -n "s/.*[\"']${key}[\"'][[:space:]]*:[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" | sed -n '1p'
}

validate_side() {
    local role="$1" file="$2"
    local adapter endpoint_url endpoint_api_key snapshot_dir state_path stale_seconds
    local recognition_url recognition_api_key recognition_tenant_id wordpress_config_extra
    local secret_backend vault_map vault_gpu_ref normalized_snapshot_dir state_dir
    local missing_recognition=()

    adapter="$(env_get "$file" ACX_DESCRIPTION_ADAPTER)"
    endpoint_url="$(env_get "$file" ACX_GPU_ENDPOINT_URL)"
    endpoint_api_key="$(env_get "$file" ACX_GPU_ENDPOINT_API_KEY)"
    snapshot_dir="$(env_get "$file" ACX_GPU_SNAPSHOT_DIR)"
    state_path="$(env_get "$file" ACX_GPU_STATE_PATH)"
    stale_seconds="$(env_get "$file" ACX_GPU_STATE_STALE_SECONDS)"

    if ! acx_is_trusted_describe_profile "$adapter"; then
        echo "ERROR [1] ${role} ACX_DESCRIPTION_ADAPTER must be florence_small, gpu_qwen30b, or gpu_qwen30b_ensemble. Set one validated live adapter (redacted length=${#adapter})." >&2
        exit 1
    fi

    if [[ "$adapter" == gpu_* ]] && ! is_http_url "$endpoint_url"; then
        echo "ERROR [2] ${role} ACX_GPU_ENDPOINT_URL must be a valid http:// or https:// URL for a gpu_* adapter (redacted length=${#endpoint_url})." >&2
        exit 1
    fi

    secret_backend="$(env_get "$file" RECOGNITION_SECRET_BACKEND)"
    if [[ "$role" == producer && "$secret_backend" == oci_vault ]]; then
        vault_map="$(env_get "$file" RECOGNITION_VAULT_SECRET_MAP)"
        vault_gpu_ref="$(vault_map_value "$vault_map" ACX_GPU_ENDPOINT_API_KEY)"
        if is_placeholder "$vault_gpu_ref" || ! printf '%s' "$vault_gpu_ref" | LC_ALL=C grep -Eq '^ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9._-]+$'; then
            echo "ERROR [3] producer oci_vault backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY OCID in RECOGNITION_VAULT_SECRET_MAP (redacted length=${#vault_gpu_ref})." >&2
            exit 1
        fi
    elif [[ -n "$endpoint_url" ]] && is_placeholder "$endpoint_api_key"; then
        echo "ERROR [3] ${role} env backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY while ACX_GPU_ENDPOINT_URL is set (redacted length=${#endpoint_api_key})." >&2
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
        echo "ERROR [4] ${role} ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH must both be set and name the same directory. Set ACX_GPU_STATE_PATH=<snapshot-dir>/gpu-state.json." >&2
        exit 1
    fi

    case "$stale_seconds" in
        ''|*[!0-9]*)
            echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
            exit 1
            ;;
    esac
    if [[ -z "${stale_seconds//0/}" ]]; then
        echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
        exit 1
    fi

    recognition_url="$(env_get "$file" ACX_RECOGNITION_URL)"
    recognition_api_key="$(env_get "$file" ACX_RECOGNITION_API_KEY)"
    recognition_tenant_id="$(env_get "$file" ACX_RECOGNITION_TENANT_ID)"
    wordpress_config_extra="$(env_get "$file" WORDPRESS_CONFIG_EXTRA)"
    if [[ "$role" == demo && -n "$wordpress_config_extra" ]]; then
        [[ -n "$recognition_url" ]] || recognition_url="$(php_define_value ACX_RECOGNITION_URL "$wordpress_config_extra")"
        [[ -n "$recognition_api_key" ]] || recognition_api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$wordpress_config_extra")"
        [[ -n "$recognition_tenant_id" ]] || recognition_tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$wordpress_config_extra")"
    fi

    [[ -n "$recognition_url" ]] || missing_recognition+=(ACX_RECOGNITION_URL)
    [[ -n "$recognition_api_key" ]] || missing_recognition+=(ACX_RECOGNITION_API_KEY)
    [[ -n "$recognition_tenant_id" ]] || missing_recognition+=(ACX_RECOGNITION_TENANT_ID)
    if (( ${#missing_recognition[@]} > 0 )); then
        printf 'ERROR [6] %s recognition config is incomplete. Set:' "$role" >&2
        printf ' %s' "${missing_recognition[@]}" >&2
        printf '. Secret values remain redacted; ACX_RECOGNITION_API_KEY length=%s.\n' "${#recognition_api_key}" >&2
        exit 1
    fi
    if ! is_http_url "$recognition_url"; then
        echo "ERROR [6] ${role} ACX_RECOGNITION_URL must be a valid http:// or https:// URL (redacted length=${#recognition_url})." >&2
        exit 1
    fi
    if is_placeholder "$recognition_api_key"; then
        echo "ERROR [6] ${role} ACX_RECOGNITION_API_KEY must not be a documented placeholder (redacted length=${#recognition_api_key})." >&2
        exit 1
    fi
    if ! is_tenant_uuid "$recognition_tenant_id" \
        || is_placeholder "$recognition_tenant_id" \
        || [[ "$recognition_tenant_id" == 00000000-0000-4000-8000-000000000001 ]]; then
        echo "ERROR [6] ${role} ACX_RECOGNITION_TENANT_ID must be an explicit RFC 4122 UUID (redacted length=${#recognition_tenant_id})." >&2
        exit 1
    fi
}

validate_side producer "$producer_env"
validate_side demo "$demo_env"

producer_recognition_url="$(env_get "$producer_env" ACX_RECOGNITION_URL)"
producer_recognition_key="$(env_get "$producer_env" ACX_RECOGNITION_API_KEY)"
producer_tenant_id="$(env_get "$producer_env" ACX_RECOGNITION_TENANT_ID)"
demo_wordpress_extra="$(env_get "$demo_env" WORDPRESS_CONFIG_EXTRA)"
demo_recognition_url="$(env_get "$demo_env" ACX_RECOGNITION_URL)"
demo_recognition_key="$(env_get "$demo_env" ACX_RECOGNITION_API_KEY)"
demo_tenant_id="$(env_get "$demo_env" ACX_RECOGNITION_TENANT_ID)"
[[ -n "$demo_recognition_url" ]] || demo_recognition_url="$(php_define_value ACX_RECOGNITION_URL "$demo_wordpress_extra")"
[[ -n "$demo_recognition_key" ]] || demo_recognition_key="$(php_define_value ACX_RECOGNITION_API_KEY "$demo_wordpress_extra")"
[[ -n "$demo_tenant_id" ]] || demo_tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$demo_wordpress_extra")"

shared_keys=(
    ACX_DESCRIPTION_ADAPTER
    ACX_GPU_ENDPOINT_URL
    ACX_GPU_SNAPSHOT_DIR
    ACX_GPU_STATE_PATH
    ACX_GPU_STATE_STALE_SECONDS
)
for key in "${shared_keys[@]}"; do
    if [[ "$(env_get "$producer_env" "$key")" != "$(env_get "$demo_env" "$key")" ]]; then
        echo "ERROR [8] producer and demo ${key} values differ. Make the two halves of the flip identical; values are redacted." >&2
        exit 1
    fi
done
producer_secret_backend="$(env_get "$producer_env" RECOGNITION_SECRET_BACKEND)"
if [[ "$producer_secret_backend" != oci_vault ]] \
    && [[ "$(env_get "$producer_env" ACX_GPU_ENDPOINT_API_KEY)" != "$(env_get "$demo_env" ACX_GPU_ENDPOINT_API_KEY)" ]]; then
    echo "ERROR [8] producer and demo ACX_GPU_ENDPOINT_API_KEY values differ. Make the two credential assertions identical; values are redacted." >&2
    exit 1
fi
if [[ "$producer_recognition_url" != "$demo_recognition_url" ]]; then
    echo "ERROR [8] producer and demo ACX_RECOGNITION_URL values differ. Make the two halves identical; values are redacted." >&2
    exit 1
fi
if [[ "$producer_recognition_key" != "$demo_recognition_key" ]]; then
    echo "ERROR [8] producer and demo ACX_RECOGNITION_API_KEY values differ. Make the two credential assertions identical; values are redacted." >&2
    exit 1
fi
if [[ "$producer_tenant_id" != "$demo_tenant_id" ]]; then
    echo "ERROR [8] producer and demo ACX_RECOGNITION_TENANT_ID values differ. Make the two halves identical; values are redacted." >&2
    exit 1
fi

adapter="$(env_get "$producer_env" ACX_DESCRIPTION_ADAPTER)"
printf 'OK: GPU env preflight passed (producer+demo, adapter=%s).\n' "$adapter"
