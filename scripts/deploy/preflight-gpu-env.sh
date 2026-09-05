#!/usr/bin/env bash
# Validate the complete producer-to-demo GPU flip before deployment.
# Docker Compose env files are data, not shell; never source either input file.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/gpu-env-contract.sh
source "${script_dir}/lib/gpu-env-contract.sh"

check_reaper=0
if [[ "${1:-}" == --check-reaper ]]; then
    check_reaper=1
    shift
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: scripts/deploy/preflight-gpu-env.sh [--check-reaper] <producer-env-file> <demo-env-file>" >&2
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
    ACX_GPU_ENDPOINT_ALLOWLIST
    ACX_GPU_CONNECT_TIMEOUT_SECONDS
    ACX_GPU_READ_TIMEOUT_SECONDS
    ACX_GPU_MAX_CONCURRENT_CALLS
    ACX_GPU_WARMUP_TIMEOUT_SECONDS
    ACX_GPU_PROMPT_VERSION
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

# The contract deliberately uses a strict Compose-dotenv subset. This keeps the
# value checked here byte-identical to the value Compose deploys: no whitespace
# around '=', export prefix, interpolation, or inline comments. Quotes around a
# complete value are supported. Count non-canonical assignments too so they
# cannot conceal an earlier safe-looking value.
validate_contract_assignments() {
    local role="$1" file="$2" key line count value
    for key in "${relevant_keys[@]}"; do
        count=0
        while IFS= read -r line || [[ -n "$line" ]]; do
            line="${line%$'\r'}"
            if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*= ]]; then
                count=$((count + 1))
                if [[ "$line" != "${key}="* ]]; then
                    echo "ERROR [7] ${role} env ${key} assignment is not canonical KEY=value syntax. Remove whitespace/export ambiguity before deployment." >&2
                    exit 1
                fi
                value="${line#*=}"
                if [[ "$value" == *'$'* || "$value" =~ [[:space:]]# ]]; then
                    echo "ERROR [7] ${role} env ${key} must not use interpolation or an inline comment. Store the exact deployed value." >&2
                    exit 1
                fi
            fi
        done < "$file"
        if (( count > 1 )); then
            echo "ERROR [7] ${role} env contains duplicate ${key} assignments. Keep only the final effective assignment before deployment (count=${count})." >&2
            exit 1
        fi
    done
}

validate_contract_assignments producer "$producer_env"
validate_contract_assignments demo "$demo_env"

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

is_placeholder() {
    local lowered
    lowered="$(printf '%s' "$1" | LC_ALL=C tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
    case "$lowered" in
        ''|*replace*|*placeholder*|*change-me*|*changeme*|*paste-key*|*paste_secret*|'<'*|'>'*) return 0 ;;
        *) return 1 ;;
    esac
}

is_http_url() {
    python3 -c '
import sys
import ipaddress
import re
from urllib.parse import urlsplit

raw = sys.argv[1]
if not raw or any(char.isspace() for char in raw):
    raise SystemExit(1)
try:
    parsed = urlsplit(raw)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if parsed.scheme not in {"http", "https"}:
    raise SystemExit(1)
host = parsed.hostname
if not parsed.netloc or host is None or parsed.username is not None or parsed.password is not None:
    raise SystemExit(1)
if parsed.netloc.endswith(":"):
    raise SystemExit(1)
if port is not None and not 1 <= port <= 65535:
    raise SystemExit(1)
if ":" in host:
    try:
        ipaddress.IPv6Address(host)
    except ValueError:
        raise SystemExit(1)
else:
    labels = host.split(".")
    if any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in labels):
        raise SystemExit(1)
raise SystemExit(0)
' "$1" 2>/dev/null
}

hostname_matches_allowlist() {
    local host="$1" allowlist="$2" entry
    host="$(printf '%s' "$host" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
    allowlist="${allowlist:-localhost,acx-gpu-burst,*.oraclevcn.com}"
    while IFS= read -r entry || [[ -n "$entry" ]]; do
        entry="$(printf '%s' "$entry" | tr -d '[:space:]' | LC_ALL=C tr '[:upper:]' '[:lower:]')"
        [[ -n "$entry" ]] || continue
        [[ "$host" == $entry ]] && return 0
    done < <(printf '%s' "$allowlist" | tr ',' '\n')
    return 1
}

ip_address_class() {
    python3 -c '
import ipaddress
import sys
try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(2)
raise SystemExit(0 if (address.is_private or address.is_loopback) and not address.is_link_local else 1)
' "$1" 2>/dev/null
}

resolved_addresses_are_private() {
    local host="$1" addresses
    addresses="$(getent ahosts "$host" 2>/dev/null | awk 'NF { print $1 }' | sort -u)" || return 1
    [[ -n "$addresses" ]] || return 1
    printf '%s\n' "$addresses" | python3 -c '
import ipaddress
import sys
addresses = [line.strip() for line in sys.stdin if line.strip()]
if not addresses:
    raise SystemExit(1)
for raw in addresses:
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        raise SystemExit(1)
    if address.is_link_local or not (address.is_private or address.is_loopback):
        raise SystemExit(1)
' 2>/dev/null
}

is_private_gpu_endpoint() {
    local url="$1" allowlist="$2" authority host address_status
    is_http_url "$url" || return 1
    authority="${url#*://}"
    authority="${authority%%/*}"
    [[ "$authority" != *@* ]] || return 1
    if [[ "$authority" == \[*\]* ]]; then
        host="${authority#\[}"
        host="${host%%\]*}"
        ip_address_class "$host"
        return
    fi
    host="${authority%%:*}"
    if ip_address_class "$host"; then
        return 0
    else
        address_status=$?
        [[ "$address_status" -eq 2 ]] || return 1
    fi
    hostname_matches_allowlist "$host" "$allowlist" || return 1
    resolved_addresses_are_private "$host"
}

is_tenant_uuid() {
    printf '%s' "$1" | LC_ALL=C grep -Eq '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
}

vault_map_value() {
    local map="$1" key="$2"
    printf '%s' "$map" | python3 -c '
import json
import sys

class DuplicateKey(ValueError):
    pass

def object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result

try:
    mapping = json.load(sys.stdin, object_pairs_hook=object_without_duplicates)
except (json.JSONDecodeError, DuplicateKey):
    raise SystemExit(1)
if not isinstance(mapping, dict) or not mapping:
    raise SystemExit(1)
if any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in mapping.items()):
    raise SystemExit(1)
value = mapping.get(sys.argv[1])
if not isinstance(value, str):
    raise SystemExit(1)
sys.stdout.write(value)
' "$key" 2>/dev/null
}

is_finite_positive_number() {
    python3 -c '
import math
import sys
try:
    value = float(sys.argv[1])
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if math.isfinite(value) and value > 0 else 1)
' "$1" 2>/dev/null
}

validate_runtime_gpu_settings() {
    local file="$1" key value entry
    for key in ACX_GPU_CONNECT_TIMEOUT_SECONDS ACX_GPU_READ_TIMEOUT_SECONDS; do
        value="$(env_get "$file" "$key")"
        if ! is_finite_positive_number "$value"; then
            echo "ERROR [10] producer ${key} must be a finite positive number (redacted length=${#value})." >&2
            exit 1
        fi
    done

    value="$(env_get "$file" ACX_GPU_MAX_CONCURRENT_CALLS)"
    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "ERROR [10] producer ACX_GPU_MAX_CONCURRENT_CALLS must be a positive integer (redacted length=${#value})." >&2
        exit 1
    fi

    value="$(env_get "$file" ACX_GPU_WARMUP_TIMEOUT_SECONDS)"
    if ! is_finite_positive_number "$value" \
        || ! python3 -c 'import sys; raise SystemExit(0 if float(sys.argv[1]) <= 3600 else 1)' "$value" 2>/dev/null; then
        echo "ERROR [10] producer ACX_GPU_WARMUP_TIMEOUT_SECONDS must be finite and in (0, 3600] (redacted length=${#value})." >&2
        exit 1
    fi

    value="$(env_get "$file" ACX_GPU_ENDPOINT_ALLOWLIST)"
    [[ -n "$value" ]] || {
        echo "ERROR [10] producer ACX_GPU_ENDPOINT_ALLOWLIST must be a non-empty comma-separated hostname pattern list." >&2
        exit 1
    }
    while IFS= read -r entry || [[ -n "$entry" ]]; do
        if [[ -z "$entry" || "$entry" =~ [[:space:]] || ! "$entry" =~ ^(\*\.)?[A-Za-z0-9][A-Za-z0-9._?-]*$ ]]; then
            echo "ERROR [10] producer ACX_GPU_ENDPOINT_ALLOWLIST contains an invalid hostname pattern; values are redacted." >&2
            exit 1
        fi
    done < <(printf '%s' "$value" | tr ',' '\n')

    value="$(env_get "$file" ACX_GPU_PROMPT_VERSION)"
    if is_placeholder "$value"; then
        echo "ERROR [10] producer ACX_GPU_PROMPT_VERSION must be non-empty and non-placeholder." >&2
        exit 1
    fi
}

reaper_execstart_is_structural() {
    python3 -c '
import shlex
import sys

raw = sys.argv[1].strip()
if raw.startswith("{"):
    marker = "argv[]="
    start = raw.find(marker)
    if start < 0:
        raise SystemExit(1)
    argv_text = raw[start + len(marker):]
    argv_text = argv_text.split(" ; ", 1)[0]
else:
    argv_text = raw
try:
    argv = shlex.split(argv_text)
except ValueError:
    raise SystemExit(1)
if argv[:4] != ["/usr/bin/python3", "-m", "infra.oci.gpu_lifecycle", "--mode"]:
    raise SystemExit(1)
if len(argv) < 5 or argv[4] != "reap":
    raise SystemExit(1)

required = {
    "--instance-id": "${GPU_INSTANCE_ID}",
    "--max-lease-seconds": "${MAX_LEASE_SECONDS}",
}
for option, expected in required.items():
    positions = [index for index, token in enumerate(argv) if token == option]
    if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != expected:
        raise SystemExit(1)
' "$1" 2>/dev/null
}

preflight_gpu_reaper() {
    local timer unit_properties exec_start fragment_path environment_files
    local environment_file optional_file instance_id="" max_lease="" value
    local environment_file_count=0
    command -v systemctl >/dev/null 2>&1 || {
        echo "ERROR [11] GPU lifecycle timers cannot be verified because systemctl is unavailable." >&2
        exit 1
    }

    for timer in acx-gpu-reap.timer acx-gpu-start.timer; do
        systemctl is-enabled --quiet "$timer" \
            && systemctl is-active --quiet "$timer" || {
            echo "ERROR [11] ${timer} must be enabled and active before the GPU flip." >&2
            exit 1
        }
    done

    unit_properties="$(systemctl show acx-gpu-reap.service \
        --property=ExecStart \
        --property=FragmentPath \
        --property=DropInPaths \
        --property=EnvironmentFiles 2>/dev/null)" || {
        echo "ERROR [11] acx-gpu-reap.service effective properties could not be read." >&2
        exit 1
    }
    exec_start="$(printf '%s\n' "$unit_properties" | sed -n 's/^ExecStart=//p')"
    fragment_path="$(printf '%s\n' "$unit_properties" | sed -n 's/^FragmentPath=//p')"
    environment_files="$(printf '%s\n' "$unit_properties" | sed -n 's/^EnvironmentFiles=//p')"
    reaper_execstart_is_structural "$exec_start" || {
        echo "ERROR [11] acx-gpu-reap.service ExecStart must be the structurally valid GPU lifecycle reaper." >&2
        exit 1
    }
    [[ "$fragment_path" == /* && "$fragment_path" != /dev/null ]] || {
        echo "ERROR [11] acx-gpu-reap.service must structurally target GPU_INSTANCE_ID and MAX_LEASE_SECONDS." >&2
        exit 1
    }

    [[ -n "$environment_files" ]] || {
        echo "ERROR [11] acx-gpu-reap.service has no effective EnvironmentFiles." >&2
        exit 1
    }
    while IFS= read -r environment_file; do
        case "$environment_file" in
            /*|'-/'*) ;;
            *) continue ;;
        esac
        optional_file=0
        if [[ "$environment_file" == -/* ]]; then
            optional_file=1
            environment_file="${environment_file#-}"
        fi
        if [[ ! -r "$environment_file" || ! -f "$environment_file" ]]; then
            if (( optional_file )); then
                continue
            fi
            echo "ERROR [11] acx-gpu-reap.service EnvironmentFile is missing or unreadable." >&2
            exit 1
        fi
        environment_file_count=$((environment_file_count + 1))
        if LC_ALL=C grep -q '^GPU_INSTANCE_ID=' "$environment_file"; then
            value="$(env_get "$environment_file" GPU_INSTANCE_ID)"
            instance_id="$value"
        fi
        if LC_ALL=C grep -q '^MAX_LEASE_SECONDS=' "$environment_file"; then
            value="$(env_get "$environment_file" MAX_LEASE_SECONDS)"
            max_lease="$value"
        fi
    done < <(printf '%s\n' "$environment_files" | tr ' ' '\n')

    (( environment_file_count > 0 )) || {
        echo "ERROR [11] acx-gpu-reap.service has no readable effective EnvironmentFiles." >&2
        exit 1
    }
    [[ "$instance_id" =~ ^ocid1\.instance\.oc[0-9]+\.[A-Za-z0-9._-]+$ \
        && "$max_lease" =~ ^[1-9][0-9]{0,4}$ ]] \
        && (( max_lease <= 86400 )) || {
        echo "ERROR [11] reaper GPU_INSTANCE_ID must be an instance OCID and MAX_LEASE_SECONDS must be in 1..86400." >&2
        exit 1
    }
    printf "MANUAL STOP fallback: oci compute instance action --action STOP --instance-id '%s'\n" "$instance_id"
}

validate_side() {
    local role="$1" file="$2"
    local adapter endpoint_url endpoint_api_key snapshot_dir state_path stale_seconds
    local recognition_url recognition_api_key recognition_tenant_id wordpress_config_extra
    local secret_backend vault_map vault_gpu_ref normalized_snapshot_dir state_dir endpoint_allowlist
    local missing_recognition=()

    adapter="$(env_get "$file" ACX_DESCRIPTION_ADAPTER)"
    endpoint_url="$(env_get "$file" ACX_GPU_ENDPOINT_URL)"
    endpoint_api_key="$(env_get "$file" ACX_GPU_ENDPOINT_API_KEY)"
    endpoint_allowlist="$(env_get "$producer_env" ACX_GPU_ENDPOINT_ALLOWLIST)"
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
    if [[ "$adapter" == gpu_* ]] && ! is_private_gpu_endpoint "$endpoint_url" "$endpoint_allowlist"; then
        echo "ERROR [9] ${role} ACX_GPU_ENDPOINT_URL must use a private/loopback IP or an ACX_GPU_ENDPOINT_ALLOWLIST hostname (redacted length=${#endpoint_url})." >&2
        exit 1
    fi

    secret_backend="$(env_get "$file" RECOGNITION_SECRET_BACKEND)"
    if [[ "$role" == producer ]]; then
        case "$secret_backend" in
            env|oci_vault) ;;
            *)
                echo "ERROR [3] producer RECOGNITION_SECRET_BACKEND must be exactly env or oci_vault (redacted length=${#secret_backend})." >&2
                exit 1
                ;;
        esac
    elif [[ -n "$secret_backend" ]]; then
        case "$secret_backend" in
            env|oci_vault) ;;
            *)
                echo "ERROR [3] demo RECOGNITION_SECRET_BACKEND, when present, must be exactly env or oci_vault (redacted length=${#secret_backend})." >&2
                exit 1
                ;;
        esac
    fi
    if [[ "$role" == producer && "$secret_backend" == oci_vault ]]; then
        vault_map="$(env_get "$file" RECOGNITION_VAULT_SECRET_MAP)"
        if ! vault_gpu_ref="$(vault_map_value "$vault_map" ACX_GPU_ENDPOINT_API_KEY)"; then
            vault_gpu_ref=""
        fi
        if is_placeholder "$vault_gpu_ref" || ! printf '%s' "$vault_gpu_ref" | LC_ALL=C grep -Eq '^ocid1\.vaultsecret\.oc[0-9]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9._-]+$'; then
            echo "ERROR [3] producer oci_vault backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY OCID in RECOGNITION_VAULT_SECRET_MAP (redacted length=${#vault_gpu_ref})." >&2
            exit 1
        fi
        if [[ -n "$endpoint_api_key" ]]; then
            echo "ERROR [3] producer oci_vault backend requires ACX_GPU_ENDPOINT_API_KEY to be blank; Vault is the only credential source (redacted length=${#endpoint_api_key})." >&2
            exit 1
        fi
    elif [[ "$role" == producer && -n "$endpoint_url" ]] && is_placeholder "$endpoint_api_key"; then
        echo "ERROR [3] ${role} env backend requires a non-placeholder ACX_GPU_ENDPOINT_API_KEY while ACX_GPU_ENDPOINT_URL is set (redacted length=${#endpoint_api_key})." >&2
        exit 1
    elif [[ "$role" == demo && -n "$endpoint_api_key" ]]; then
        echo "ERROR [3] demo ACX_GPU_ENDPOINT_API_KEY must be absent; only the producer consumes this secret (redacted length=${#endpoint_api_key})." >&2
        exit 1
    fi

    if [[ "$snapshot_dir" != /run/acx || "$state_path" != /run/acx/gpu-state.json ]]; then
        echo "ERROR [4] ${role} ACX_GPU_SNAPSHOT_DIR and ACX_GPU_STATE_PATH must be /run/acx and /run/acx/gpu-state.json, respectively, as required by the compose mount and lifecycle units." >&2
        exit 1
    fi

    case "$stale_seconds" in
        ''|*[!0-9]*)
            echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
            exit 1
            ;;
    esac
    if [[ -z "${stale_seconds//0/}" ]] || ! is_finite_positive_number "$stale_seconds"; then
        echo "ERROR [5] ${role} ACX_GPU_STATE_STALE_SECONDS must be a positive integer (redacted length=${#stale_seconds})." >&2
        exit 1
    fi

    if [[ "$role" == demo ]]; then
        recognition_url="$(env_get "$file" ACX_RECOGNITION_URL)"
        recognition_api_key="$(env_get "$file" ACX_RECOGNITION_API_KEY)"
        recognition_tenant_id="$(env_get "$file" ACX_RECOGNITION_TENANT_ID)"
        wordpress_config_extra="$(env_get "$file" WORDPRESS_CONFIG_EXTRA)"
        if [[ -n "$recognition_url" || -n "$recognition_api_key" || -n "$recognition_tenant_id" ]]; then
            echo "ERROR [6] demo standalone ACX_RECOGNITION_* entries are ambiguous. Remove them and edit only WORDPRESS_CONFIG_EXTRA PHP constants." >&2
            exit 1
        fi
        recognition_url="$(php_define_value ACX_RECOGNITION_URL "$wordpress_config_extra")"
        recognition_api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$wordpress_config_extra")"
        recognition_tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$wordpress_config_extra")"

        [[ -n "$recognition_url" ]] || missing_recognition+=(ACX_RECOGNITION_URL)
        [[ -n "$recognition_api_key" ]] || missing_recognition+=(ACX_RECOGNITION_API_KEY)
        [[ -n "$recognition_tenant_id" ]] || missing_recognition+=(ACX_RECOGNITION_TENANT_ID)
        if (( ${#missing_recognition[@]} > 0 )); then
            printf 'ERROR [6] demo recognition config is incomplete. Set:' >&2
            printf ' %s' "${missing_recognition[@]}" >&2
            printf '. Secret values remain redacted; ACX_RECOGNITION_API_KEY length=%s.\n' "${#recognition_api_key}" >&2
            exit 1
        fi
        if ! is_http_url "$recognition_url"; then
            echo "ERROR [6] demo ACX_RECOGNITION_URL must be a valid http:// or https:// URL (redacted length=${#recognition_url})." >&2
            exit 1
        fi
        if is_placeholder "$recognition_api_key"; then
            echo "ERROR [6] demo ACX_RECOGNITION_API_KEY must not be a documented placeholder (redacted length=${#recognition_api_key})." >&2
            exit 1
        fi
        if ! is_tenant_uuid "$recognition_tenant_id" \
            || is_placeholder "$recognition_tenant_id" \
            || [[ "$recognition_tenant_id" == 00000000-0000-4000-8000-000000000001 ]]; then
            echo "ERROR [6] demo ACX_RECOGNITION_TENANT_ID must be an explicit RFC 4122 UUID (redacted length=${#recognition_tenant_id})." >&2
            exit 1
        fi
    fi
}

if (( check_reaper )); then
    preflight_gpu_reaper
fi

validate_runtime_gpu_settings "$producer_env"
validate_side producer "$producer_env"
validate_side demo "$demo_env"

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
adapter="$(env_get "$producer_env" ACX_DESCRIPTION_ADAPTER)"
printf 'OK: GPU env preflight passed (producer+demo, adapter=%s).\n' "$adapter"
