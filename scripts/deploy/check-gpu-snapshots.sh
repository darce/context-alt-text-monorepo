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
state_stale_seconds=${ACX_GPU_STATE_STALE_SECONDS:-180}
load_stale_seconds=${ACX_DESCRIBE_LOAD_STALE_SECONDS:-120}
reader_uid=${ACX_GPU_READER_UID:-10001}
now_epoch=${ACX_NOW_EPOCH:-$(date +%s)}
config_only=${ACX_GPU_SNAPSHOT_CONFIG_ONLY:-0}
load_environments="dev staging prod"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

is_positive_number() {
    awk -v value="$1" 'BEGIN { exit !(value ~ /^[0-9]+([.][0-9]+)?$/ && value > 0) }'
}

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
    local label=$1 path=$2 budget=$3 readability_rc=0 written_at age
    [ -e "$path" ] || die "missing $label snapshot: $path"
    [ -f "$path" ] || die "$label snapshot is not a regular file: $path"
    reader_can_read "$path" || readability_rc=$?
    if [ "$readability_rc" -eq 2 ]; then
        die "cannot verify $label snapshot readability as uid $reader_uid; run as root"
    elif [ "$readability_rc" -ne 0 ]; then
        die "$label snapshot is unreadable by uid $reader_uid: $path"
    fi

    written_at=$(python3 -c \
        'import json, math, sys; value=json.load(open(sys.argv[1], encoding="utf-8")).get("written_at"); assert not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value), "written_at must be finite epoch seconds"; print(value)' \
        "$path" 2>/dev/null) || die "$label snapshot has no valid written_at: $path"
    age=$(awk -v now="$now_epoch" -v written="$written_at" 'BEGIN { printf "%.6f", now - written }')
    awk -v age="$age" 'BEGIN { exit !(age >= 0) }' ||
        die "$label snapshot written_at is in the future: $written_at"
    awk -v age="$age" -v budget="$budget" 'BEGIN { exit !(age <= budget) }' ||
        die "stale $label snapshot: age ${age}s exceeds ${budget}s budget ($path)"
}

check_snapshot "GPU state" "$unit_state_path" "$state_stale_seconds"
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
    check_snapshot "describe load (${environment})" \
        "${environment_dir}/describe-load.json" "$load_stale_seconds"
done

echo "OK: GPU state and per-environment describe-load deployment contract is fresh"
