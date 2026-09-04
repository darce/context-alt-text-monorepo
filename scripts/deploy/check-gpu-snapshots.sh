#!/usr/bin/env bash
# Fail-closed deployment and freshness check for the two /run/acx snapshots.

if [ -z "${BASH_VERSION:-}" ]; then
    echo "ERROR: $0 must run under bash" >&2
    exit 2
fi
set -euo pipefail

# The deploy path ships this checker to the VM over stdin (`bash -s`), which
# leaves BASH_SOURCE unset; `set -u` then makes an unguarded read fatal, and a
# bare `cd ""/../..` would silently resolve repo_root to `/`. A piped run has no
# checkout, so its paths must arrive through the environment instead.
script_path=${BASH_SOURCE[0]:-}
if [ -n "$script_path" ]; then
    repo_root=$(cd "$(dirname "$script_path")/../.." && pwd)
else
    repo_root=
fi
compose_file=${ACX_GPU_COMPOSE_FILE:-${repo_root:+${repo_root}/apps/prototype-description-service/docker-compose.env.yml}}
install_script=${ACX_GPU_INSTALL_SCRIPT:-${repo_root:+${repo_root}/scripts/deploy/gpu-lifecycle-install.sh}}
deployments_file=${ACX_GPU_DEPLOYMENTS_FILE:-${repo_root:+${repo_root}/scripts/deploy/gpu-snapshot-deployments.conf}}
state_stale_seconds=${ACX_GPU_STATE_STALE_SECONDS:-180}
load_stale_seconds=${ACX_DESCRIBE_LOAD_STALE_SECONDS:-120}
reader_uid=${ACX_GPU_READER_UID:-10001}
now_epoch=${ACX_NOW_EPOCH:-$(date +%s)}
config_only=${ACX_GPU_SNAPSHOT_CONFIG_ONLY:-0}
load_environments=

die() {
    echo "ERROR: $*" >&2
    exit 1
}

is_positive_number() {
    awk -v value="$1" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value > 0) }'
}

append_deployment() {
    local environment=$1 source=$2
    [[ "$environment" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] ||
        die "invalid GPU snapshot deployment '$environment' in $source"
    case " $load_environments " in
        *" $environment "*) die "duplicate GPU snapshot deployment '$environment' in $source" ;;
    esac
    load_environments="${load_environments:+${load_environments} }${environment}"
}

load_deployments() {
    local environment line_number=0 source
    if [ "${ACX_GPU_DEPLOYMENTS+x}" = x ]; then
        source=ACX_GPU_DEPLOYMENTS
        # The transported form is comma-delimited so remote `bash -s` callers
        # do not need a checkout containing the registry.
        while IFS= read -r environment; do
            [ -n "$environment" ] || die "$source must not contain empty entries"
            append_deployment "$environment" "$source"
        done < <(tr ',' '\n' <<<"$ACX_GPU_DEPLOYMENTS")
    else
        [ -n "$deployments_file" ] ||
            die "no repo checkout to read GPU snapshot deployments from; set ACX_GPU_DEPLOYMENTS"
        [ -r "$deployments_file" ] ||
            die "GPU snapshot deployments file is missing or unreadable: $deployments_file"
        source=$deployments_file
        while IFS= read -r environment || [ -n "$environment" ]; do
            line_number=$((line_number + 1))
            [ -n "$environment" ] ||
                die "empty GPU snapshot deployment at ${source}:${line_number}"
            append_deployment "$environment" "${source}:${line_number}"
        done < "$deployments_file"
    fi
    [ -n "$load_environments" ] || die "GPU snapshot deployment registry is empty: $source"
}

load_deployments

unit_path_for_flag() {
    local flag=$1
    local -a paths
    local path
    local path_count=0
    [ -n "$install_script" ] ||
        die "no repo checkout to read lifecycle units from; set ACX_GPU_UNIT_STATE_PATH and ACX_GPU_UNIT_LOAD_DIR, or ACX_GPU_INSTALL_SCRIPT"
    [ -r "$install_script" ] || die "lifecycle install script is missing or unreadable: $install_script"
    while IFS= read -r path; do
        paths[$path_count]=$path
        path_count=$((path_count + 1))
    done < <(
        sed -nE "s/.*${flag}[[:space:]]+([^[:space:]\\\\]+).*/\\1/p" "$install_script" |
            sort -u
    )
    [ "$path_count" -eq 1 ] ||
        die "lifecycle units do not have exactly one agreeing ${flag} path in $install_script"
    printf '%s\n' "${paths[0]}"
}

# Unit ExecStart flags are the authority for what the host actually writes.
# Test fixtures may override them, but production adds no fifth path literal.
unit_state_path=${ACX_GPU_UNIT_STATE_PATH:-}
unit_load_dir=${ACX_GPU_UNIT_LOAD_DIR:-}
[ -n "$unit_state_path" ] || unit_state_path=$(unit_path_for_flag --gpu-state-json)
[ -n "$unit_load_dir" ] || unit_load_dir=$(unit_path_for_flag --load-dir)
state_path=${ACX_GPU_STATE_PATH:-$unit_state_path}
state_dir=${ACX_GPU_SNAPSHOT_DIR:-${unit_state_path%/*}}
load_dir=${ACX_DESCRIBE_LOAD_DIR:-$unit_load_dir}

[ "$state_path" = "$unit_state_path" ] ||
    die "ACX_GPU_STATE_PATH disagrees with lifecycle units: $state_path != $unit_state_path"
[ "$state_dir" = "${unit_state_path%/*}" ] ||
    die "ACX_GPU_SNAPSHOT_DIR disagrees with lifecycle units: $state_dir != ${unit_state_path%/*}"
[ "$load_dir" = "$unit_load_dir" ] ||
    die "ACX_DESCRIBE_LOAD_DIR disagrees with lifecycle units: $load_dir != $unit_load_dir"
[ "$state_dir" != "$load_dir" ] ||
    die "GPU state and describe-load units must use separate snapshot directories"
is_positive_number "$state_stale_seconds" ||
    die "ACX_GPU_STATE_STALE_SECONDS must be a positive number"
is_positive_number "$load_stale_seconds" ||
    die "ACX_DESCRIBE_LOAD_STALE_SECONDS must be a positive number"
[[ "$reader_uid" =~ ^[0-9]+$ ]] || die "ACX_GPU_READER_UID must be numeric"
[[ "$now_epoch" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "ACX_NOW_EPOCH must be numeric"
[[ "$config_only" =~ ^[01]$ ]] || die "ACX_GPU_SNAPSHOT_CONFIG_ONLY must be 0 or 1"
[ -n "$compose_file" ] ||
    die "no repo checkout to read the compose file from; set ACX_GPU_COMPOSE_FILE"
[ -r "$compose_file" ] || die "compose file is missing or unreadable: $compose_file"

api_block=$(awk '
    /^  api:$/ { in_api = 1; next }
    in_api && /^  [A-Za-z0-9_-]+:$/ { exit }
    in_api && $0 !~ /^[[:space:]]*#/ { print }
' "$compose_file")
[ -n "$api_block" ] || die "compose file has no api service: $compose_file"

# Require the exact template mount deployment uses. The environment token is
# intentionally retained: every stack renders it to its own isolated subdir.
rendered_state_mount="${state_dir}:${state_dir}:ro"
volume_specs=$(awk '
    /^[[:space:]]*-[[:space:]]/ {
        sub(/^[[:space:]]*-[[:space:]]*/, "")
        if (index($0, ":") > 0) print
    }
' <<<"$api_block")
compose_load_paths=$(sed -nE \
    's/^[[:space:]]*-[[:space:]]*ACX_DESCRIBE_LOAD_PATH=([^[:space:]]+)[[:space:]]*$/\1/p' \
    <<<"$api_block")
[ "$(wc -l <<<"$compose_load_paths" | tr -d ' ')" -eq 1 ] ||
    die "compose api service must set exactly one ACX_DESCRIBE_LOAD_PATH"
compose_load_filename=${compose_load_paths##*/}
compose_load_env_dir=${compose_load_paths%/*}
compose_load_env_token=${compose_load_env_dir##*/}
compose_load_parent=${compose_load_env_dir%/*}
[ "$compose_load_filename" = "describe-load.json" ] ||
    die "compose ACX_DESCRIBE_LOAD_PATH must end in describe-load.json"
[ "$compose_load_env_token" = '${ACX_ENV}' ] ||
    die 'compose ACX_DESCRIBE_LOAD_PATH must use the ${ACX_ENV} subdirectory'
[ "$compose_load_parent" = "$unit_load_dir" ] ||
    die "compose-derived load parent disagrees with lifecycle --load-dir: $compose_load_parent != $unit_load_dir"
rendered_load_mount="${compose_load_env_dir}:${compose_load_env_dir}"
state_source_mounts=$(grep -F -- "${state_dir}:" <<<"$volume_specs" || true)
load_source_mounts=$(grep -F -- "${unit_load_dir}" <<<"$volume_specs" || true)
if [ "$state_source_mounts" != "$rendered_state_mount" ]; then
    die "compose api service has no agreeing read-only state mount ($rendered_state_mount)"
fi
if [ "$load_source_mounts" != "$rendered_load_mount" ]; then
    die "compose api service has no agreeing writable load mount ($rendered_load_mount)"
fi
if ! grep -Fq -- "ACX_GPU_STATE_PATH=${state_path}" <<<"$api_block"; then
    die "compose api service does not pass the agreeing ACX_GPU_STATE_PATH"
fi

if [ "$config_only" -eq 1 ]; then
    echo "OK: GPU snapshot lifecycle and compose configuration agree"
    exit 0
fi

reader_can_read() {
    local path=$1 current_uid
    current_uid=$(id -u)
    if [ "$current_uid" = "$reader_uid" ]; then
        test -r "$path"
    elif [ "$current_uid" = 0 ] && command -v setpriv >/dev/null 2>&1; then
        setpriv --reuid="$reader_uid" --regid="$reader_uid" --clear-groups test -r "$path"
    else
        return 2
    fi
}

writer_can_write_directory() {
    local path=$1 current_uid
    current_uid=$(id -u)
    if [ "$current_uid" = "$reader_uid" ]; then
        test -w "$path"
    elif [ "$current_uid" = 0 ] && command -v setpriv >/dev/null 2>&1; then
        setpriv --reuid="$reader_uid" --regid="$reader_uid" --clear-groups test -w "$path"
    else
        return 2
    fi
}

check_snapshot() {
    local label=$1 kind=$2 path=$3 budget=$4 readability_rc=0 written_at age
    [ -e "$path" ] || die "missing $label snapshot: $path"
    [ -f "$path" ] || die "$label snapshot is not a regular file: $path"
    reader_can_read "$path" || readability_rc=$?
    if [ "$readability_rc" -eq 2 ]; then
        die "cannot verify $label snapshot readability as uid $reader_uid; run as root"
    elif [ "$readability_rc" -ne 0 ]; then
        die "$label snapshot is unreadable by uid $reader_uid: $path"
    fi

    written_at=$(python3 -c '
import json
import math
import sys

kind, path = sys.argv[1:]


def fail(message):
    print(f"{path}: {message}", file=sys.stderr)
    raise SystemExit(1)


try:
    with open(path, encoding="utf-8") as snapshot_file:
        payload = json.load(snapshot_file)
except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
    fail(f"snapshot must contain valid JSON: {exc}")

if not isinstance(payload, dict):
    fail("snapshot root must be an object")

written_at = payload.get("written_at")
if (
    isinstance(written_at, bool)
    or not isinstance(written_at, (int, float))
    or not math.isfinite(written_at)
):
    fail("written_at must be finite epoch seconds")

if kind == "gpu-state":
    # Standalone mirror: parity-tested against GpuLifecycleState because the
    # production checker is piped to a host where the repository is absent.
    valid_gpu_states = ("stopped", "starting", "warming", "ready", "degraded")
    if "state" not in payload:
        fail("state is required")
    state = payload["state"]
    if not isinstance(state, str) or state not in valid_gpu_states:
        fail(f"state must be one of {valid_gpu_states}")

    instance_id = payload.get("instance_id")
    if instance_id is not None and (
        not isinstance(instance_id, str) or not instance_id.strip()
    ):
        fail("instance_id must be null or a non-blank string")

    reason = payload.get("reason")
    if state == "degraded":
        if not isinstance(reason, str) or not reason.strip():
            fail("reason must be a non-blank string for degraded state")
    elif reason is not None:
        fail("reason is only valid for degraded state")

    if "since" in payload:
        since = payload["since"]
        if (
            isinstance(since, bool)
            or not isinstance(since, (int, float))
            or not math.isfinite(since)
        ):
            fail("since must be finite epoch seconds when present")
        if since > written_at:
            fail("since must not be later than written_at")
elif kind == "load":
    for field in ("queue_depth", "in_flight"):
        if field not in payload:
            fail(f"{field} is required")
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail(f"{field} must be a non-negative integer")
    if "batch_in_progress" in payload and not isinstance(
        payload["batch_in_progress"], bool
    ):
        fail("batch_in_progress must be a boolean when present")
else:
    fail(f"unknown snapshot kind {kind!r}")

print(written_at)
' "$kind" "$path") || die "$label snapshot failed schema validation: $path"
    age=$(awk -v now="$now_epoch" -v written="$written_at" 'BEGIN { printf "%.6f", now - written }')
    awk -v age="$age" 'BEGIN { exit !(age >= 0) }' ||
        die "$label snapshot written_at is in the future: $written_at ($path)"
    awk -v age="$age" -v budget="$budget" 'BEGIN { exit !(age <= budget) }' ||
        die "stale $label snapshot: age ${age}s exceeds ${budget}s budget ($path)"
}

check_snapshot "GPU state" "gpu-state" "$unit_state_path" "$state_stale_seconds"
for environment in $load_environments; do
    environment_dir="${unit_load_dir}/${environment}"
    [ -d "$environment_dir" ] ||
        die "missing describe-load environment directory: $environment_dir"
    writable_rc=0
    writer_can_write_directory "$environment_dir" || writable_rc=$?
    if [ "$writable_rc" -eq 2 ]; then
        die "cannot verify describe-load directory writability as uid $reader_uid; run as root"
    elif [ "$writable_rc" -ne 0 ]; then
        die "describe-load directory is not writable by uid $reader_uid: $environment_dir"
    fi
    check_snapshot "describe load (${environment})" "load" \
        "${environment_dir}/describe-load.json" "$load_stale_seconds"
done

echo "OK: GPU state and per-environment describe-load deployment contract is fresh"
