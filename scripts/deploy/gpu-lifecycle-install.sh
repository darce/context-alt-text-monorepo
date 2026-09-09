#!/usr/bin/env bash
# Install the burst-GPU lifecycle controller on acx-backend (GPUW-1).
#
# Why this exists rather than cloud-init: cloud-init runs once at first boot,
# while this installer can converge the lifecycle units on an existing host.
# [RLSE-11] rejects a deploy step that is a human click-path executed more than
# once, so this is idempotent and re-runnable.
#
# Installs two timers against the same load dump:
#   acx-gpu-start  -- START the burst GPU when describe work is waiting
#   acx-gpu-reap   -- STOP it when the work drains, and unconditionally at the
#                     max-lease cap (the cost backstop; see reaper.py)
#
# The recognition deploy pipeline is the normal entrypoint. Direct use remains
# available for recovery and local dry-run inspection:
#   scripts/deploy/gpu-lifecycle-install.sh --user ubuntu \
#     --host acx-backend.tail1a44b8.ts.net \
#     --ready-url http://<gpu-private-ip>:8000/health
# READY_URL has no default: production installs must name the endpoint that
# supplies current, evidence-backed GPU readiness.
# Dry run (print what would change, touch nothing):
#   scripts/deploy/gpu-lifecycle-install.sh --host ... --dry-run

set -euo pipefail

sha256_file() {
    [ "$#" -eq 1 ] || {
        echo "error: sha256_file requires exactly one path" >&2
        return 2
    }
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1"
        return
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1"
        return
    fi
    echo "error: neither sha256sum nor shasum is available" >&2
    return 127
}

verify_gpu_lifecycle_timers() {
    [ "$#" -eq 5 ] || {
        echo "error: effective-unit verification requires four expected hashes and max lease" >&2
        return 2
    }
    local expected_start_service_hash=$1 expected_start_timer_hash=$2
    local expected_reap_service_hash=$3 expected_reap_timer_hash=$4
    local expected_max_lease=$5 effective_unit_dir expected_env_file
    local unit expected_hash fragment_path drop_in_paths effective_hash exec_start
    effective_unit_dir="${ACX_EFFECTIVE_SYSTEMD_DIR:-/etc/systemd/system}"
    expected_env_file="${ACX_EXPECTED_ENV_FILE:-/etc/acx/gpu-lifecycle.env}"
    if [[ ! "$expected_max_lease" =~ ^[0-9]+$ ]] \
        || ! [ "$expected_max_lease" -ge 1 ] 2>/dev/null \
        || ! [ "$expected_max_lease" -le 86400 ] 2>/dev/null; then
        echo "error: effective reaper max lease must be an integer from 1 through 86400" >&2
        return 1
    fi

    for unit in \
        acx-gpu-start.service acx-gpu-start.timer \
        acx-gpu-reap.service acx-gpu-reap.timer; do
        case "$unit" in
            acx-gpu-start.service) expected_hash=$expected_start_service_hash ;;
            acx-gpu-start.timer) expected_hash=$expected_start_timer_hash ;;
            acx-gpu-reap.service) expected_hash=$expected_reap_service_hash ;;
            acx-gpu-reap.timer) expected_hash=$expected_reap_timer_hash ;;
        esac
        fragment_path=$(systemctl show "$unit" --property=FragmentPath --value) || {
            echo "error: could not resolve the effective fragment for $unit" >&2
            return 1
        }
        if [ "$fragment_path" != "${effective_unit_dir}/${unit}" ]; then
            echo "error: $unit effective fragment is unexpected: ${fragment_path:-<empty>}" >&2
            return 1
        fi
        drop_in_paths=$(systemctl show "$unit" --property=DropInPaths --value) || {
            echo "error: could not inspect drop-ins for $unit" >&2
            return 1
        }
        if [ -n "$drop_in_paths" ]; then
            echo "error: $unit has unexpected effective drop-ins: $drop_in_paths" >&2
            return 1
        fi
        effective_hash=$(sha256_file "$fragment_path" | awk '{print $1}') || {
            echo "error: could not hash the effective fragment for $unit" >&2
            return 1
        }
        if [ "$effective_hash" != "$expected_hash" ]; then
            echo "error: $unit effective content does not match this release" >&2
            return 1
        fi
    done

    exec_start=$(systemctl show acx-gpu-reap.service --property=ExecStart --value) || {
        echo "error: could not inspect the effective acx-gpu-reap.service ExecStart" >&2
        return 1
    }
    case "$exec_start" in
        *"--mode reap"*"--max-lease-seconds"*'${MAX_LEASE_SECONDS}'*) ;;
        *)
            echo "error: effective acx-gpu-reap.service lacks the max-lease argument" >&2
            return 1
            ;;
    esac
    grep -Fqx "MAX_LEASE_SECONDS=${expected_max_lease}" "$expected_env_file" || {
        echo "error: effective reaper max lease is not ${expected_max_lease}s" >&2
        return 1
    }

    systemctl is-enabled --quiet acx-gpu-reap.timer || {
        echo "error: acx-gpu-reap.timer is not enabled" >&2
        return 1
    }
    systemctl is-active --quiet acx-gpu-reap.timer || {
        echo "error: acx-gpu-reap.timer is not active" >&2
        return 1
    }
    echo "acx-gpu-reap.timer enabled active"
}

verify_gpu_lifecycle_start_timer() {
    systemctl is-enabled --quiet acx-gpu-start.timer || {
        echo "error: acx-gpu-start.timer is not enabled" >&2
        return 1
    }
    systemctl is-active --quiet acx-gpu-start.timer || {
        echo "error: acx-gpu-start.timer is not active" >&2
        return 1
    }
    echo "acx-gpu-start.timer enabled active"
}

verify_gpu_intent_path() {
    [ "$#" -eq 1 ] || {
        echo "error: intent-path verification requires one expected hash" >&2
        return 2
    }
    local expected_hash=$1 effective_unit_dir fragment_path drop_in_paths effective_hash
    effective_unit_dir="${ACX_EFFECTIVE_SYSTEMD_DIR:-/etc/systemd/system}"
    fragment_path=$(systemctl show acx-gpu-intent.path --property=FragmentPath --value) || {
        echo "error: could not resolve the effective fragment for acx-gpu-intent.path" >&2
        return 1
    }
    if [ "$fragment_path" != "${effective_unit_dir}/acx-gpu-intent.path" ]; then
        echo "error: acx-gpu-intent.path effective fragment is unexpected: ${fragment_path:-<empty>}" >&2
        return 1
    fi
    drop_in_paths=$(systemctl show acx-gpu-intent.path --property=DropInPaths --value) || {
        echo "error: could not inspect drop-ins for acx-gpu-intent.path" >&2
        return 1
    }
    if [ -n "$drop_in_paths" ]; then
        echo "error: acx-gpu-intent.path has unexpected effective drop-ins: $drop_in_paths" >&2
        return 1
    fi
    effective_hash=$(sha256_file "$fragment_path" | awk '{print $1}') || {
        echo "error: could not hash the effective fragment for acx-gpu-intent.path" >&2
        return 1
    }
    if [ "$effective_hash" != "$expected_hash" ]; then
        echo "error: acx-gpu-intent.path effective content does not match this release" >&2
        return 1
    fi
    systemctl is-enabled --quiet acx-gpu-intent.path || {
        echo "error: acx-gpu-intent.path is not enabled" >&2
        return 1
    }
    systemctl is-active --quiet acx-gpu-intent.path || {
        echo "error: acx-gpu-intent.path is not active" >&2
        return 1
    }
    echo "acx-gpu-intent.path enabled active"
}

fence_gpu_intent_path() {
    local load_state

    # The path watcher can launch START from an operator intent write. Disable
    # and stop it before replacing any release or effective unit, and tolerate
    # fresh hosts where the watcher has not been installed yet.
    sudo systemctl disable --now acx-gpu-intent.path || {
        if ! load_state=$(systemctl show acx-gpu-intent.path --property=LoadState --value) \
            || [ "$load_state" != not-found ]; then
            echo 'error: failed to disable acx-gpu-intent.path' >&2
            return 1
        fi
    }
}

purge_stale_gpu_reaper_units() {
    local unit load_state
    # cloud-init used these units before the installer became the sole owner.
    # Disable both forms before removing their fragments so a provisioned host
    # converges even when the old timer is currently active.
    for unit in acx-gpu-idle-reaper.timer acx-gpu-idle-reaper.service; do
        sudo systemctl disable --now "$unit" || {
            if ! load_state=$(systemctl show "$unit" --property=LoadState --value) \
                || [ "$load_state" != not-found ]; then
                echo "error: failed to disable stale $unit" >&2
                return 1
            fi
        }
        sudo rm -f "/etc/systemd/system/$unit"
    done
    sudo systemctl daemon-reload
}

ensure_acx_api_group() {
    # systemd resolves SupplementaryGroups through NSS before it forks ExecStart.
    # A bare numeric gid with no /etc/group entry is not resolvable, so the unit
    # dies at status=216/GROUP with "Failed to determine supplementary groups:
    # No such process" -- before a single line of lifecycle code runs. Print the
    # name the units must use on stdout; diagnostics go to stderr.
    local gid=$1 name=$2 existing fallback_name
    existing=$(getent group "$gid" | cut -d: -f1)
    if [ -n "$existing" ]; then
        if [ "$existing" != "$name" ]; then
            echo "gpu-lifecycle: gid $gid is already named '$existing'; units will use that name" >&2
        fi
        printf '%s\n' "$existing"
        return 0
    fi
    if ! sudo groupadd -r -g "$gid" "$name" >&2; then
        fallback_name="acxgid${gid}"
        sudo groupadd -r -g "$gid" "$fallback_name" >&2 || {
            echo "error: could not provision a resolvable group for gid $gid" >&2
            return 1
        }
        name="$fallback_name"
    fi
    getent group "$gid" >/dev/null || {
        echo "error: created group '$name' but NSS does not resolve GID $gid" >&2
        return 1
    }
    printf '%s\n' "$name"
}

load_snapshots_ready_for_reaper_proof() {
    # Immediate reaper proof needs published describe-load.json files. A fresh
    # host has the directories (tmpfiles) but no producer snapshots yet; starting
    # acx-gpu-reap.service then fails closed and aborts install before deploy
    # prod can publish them. Runtime timer ticks remain fail-closed.
    local dir snapshot
    local ready=0
    for dir in /run/acx-write/*/; do
        if [ ! -d "$dir" ]; then
            echo "gpu-lifecycle: no load snapshot directories yet; deferring immediate reaper proof until producer deploy publishes describe-load.json" >&2
            return 1
        fi
        snapshot="${dir}describe-load.json"
        if [ ! -s "$snapshot" ]; then
            echo "gpu-lifecycle: missing load snapshot ${snapshot}; deferring immediate reaper proof until producer deploy publishes it" >&2
            return 1
        fi
        ready=1
    done
    if [ "$ready" -ne 1 ]; then
        echo "gpu-lifecycle: no load snapshot directories yet; deferring immediate reaper proof until producer deploy publishes describe-load.json" >&2
        return 1
    fi
    return 0
}

activate_gpu_lifecycle_timers() {
    [ "$#" -eq 6 ] || {
        echo "error: lifecycle activation requires four expected hashes, max lease, and intent-path hash" >&2
        return 2
    }
    local expected_intent_path_hash=$6
    sudo systemctl enable --now acx-gpu-reap.timer
    if load_snapshots_ready_for_reaper_proof; then
        sudo systemctl start acx-gpu-reap.service
    fi
    verify_gpu_lifecycle_timers "$1" "$2" "$3" "$4" "$5"

    sudo systemctl enable --now acx-gpu-start.timer
    verify_gpu_lifecycle_start_timer

    sudo systemctl enable --now acx-gpu-intent.path
    verify_gpu_intent_path "$expected_intent_path_hash"
}

fence_gpu_lifecycle_start() {
    local lock_path="${ACX_GPU_LIFECYCLE_LOCK_PATH:-/var/lib/acx-gpu/lifecycle.lock}"
    local load_state

    # `systemctl stop` waits for an in-flight oneshot to terminate. The shared
    # flock then proves no older START process survived outside systemd's view
    # before cleanup is allowed to invoke the reaper.
    # Fresh hosts have neither unit. Accept a failed disable/stop only when
    # systemd positively identifies that unit as absent; query errors and
    # failures affecting existing units must still abort the transaction.
    sudo systemctl disable --now acx-gpu-start.timer || {
        if ! load_state=$(systemctl show acx-gpu-start.timer --property=LoadState --value) \
            || [ "$load_state" != not-found ]; then
            echo 'error: failed to disable acx-gpu-start.timer' >&2
            return 1
        fi
    }
    sudo systemctl stop acx-gpu-start.service || {
        if ! load_state=$(systemctl show acx-gpu-start.service --property=LoadState --value) \
            || [ "$load_state" != not-found ]; then
            echo 'error: failed to stop acx-gpu-start.service' >&2
            return 1
        fi
    }
    if systemctl is-active --quiet acx-gpu-start.timer; then
        echo 'error: acx-gpu-start.timer remained active after disable' >&2
        return 1
    fi
    if systemctl is-active --quiet acx-gpu-start.service; then
        echo 'error: acx-gpu-start.service remained active after stop' >&2
        return 1
    fi

    sudo mkdir -p "${lock_path%/*}"
    sudo touch "$lock_path"
    sudo chown ubuntu:ubuntu "${lock_path%/*}" "$lock_path"
    sudo chmod 0700 "${lock_path%/*}"
    sudo chmod 0600 "$lock_path"
    sudo flock --wait 120 "$lock_path" true || {
        echo 'error: timed out waiting for the GPU lifecycle lock to quiesce' >&2
        return 1
    }
}

validate_gpu_lifecycle_snapshot() {
    local snapshot_dir=$1 allow_missing_intent_path=${2:-0} artifact section key
    for artifact in gpu-lifecycle.env acx-gpu.conf acx-gpu-start.service \
        acx-gpu-start.timer acx-gpu-reap.service acx-gpu-reap.timer \
        acx-gpu-intent.path; do
        if [ "$artifact" = acx-gpu-intent.path ] \
            && [ "$allow_missing_intent_path" -eq 1 ] \
            && [ ! -e "$snapshot_dir/$artifact" ]; then
            # Releases created before the intent watcher are valid rollback
            # targets; the next generation installs the watcher.
            continue
        fi
        if [ ! -f "$snapshot_dir/$artifact" ] \
            || [ ! -r "$snapshot_dir/$artifact" ] \
            || [ ! -s "$snapshot_dir/$artifact" ]; then
            echo "error: incomplete rollback snapshot: $snapshot_dir/$artifact" >&2
            return 1
        fi
        case "$artifact" in
            *.service) section=Service; key=ExecStart ;;
            *.timer) section=Timer; key=OnUnitActiveSec ;;
            *.path) section=Path; key=PathChanged ;;
            *) continue ;;
        esac
        # A truncated but non-empty unit cannot restore the STOP backstop.
        # Check the key in its actual section, including later empty resets.
        if ! awk -v section="$section" -v key="$key" '
            /^[[:space:]]*[#;]/ { next }
            /^[[:space:]]*\[/ {
                active = ($0 ~ "^[[:space:]]*\\[" section "\\][[:space:]]*$")
            }
            active && $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
                value = $0
                sub(/^[^=]*=[[:space:]]*/, "", value)
                valid = (value ~ /[^[:space:]]/)
            }
            END { exit !valid }
        ' "$snapshot_dir/$artifact"; then
            echo "error: incomplete rollback snapshot: $snapshot_dir/$artifact lacks $section.$key" >&2
            return 1
        fi
    done
}

snapshot_gpu_lifecycle_release() {
    local previous_release=$1 snapshot_stage="" snapshot_dir artifact
    local intent_path_available=0
    [ -e /etc/systemd/system/acx-gpu-intent.path ] && intent_path_available=1
    snapshot_dir="$previous_release/systemd"
    if [ ! -d "$previous_release/systemd" ]; then
        # Only the final rename publishes a snapshot. A copy failure must not
        # leave a directory that the next deploy mistakes for a complete one.
        snapshot_stage=$(sudo mktemp -d "$previous_release/.systemd.XXXXXX") || return 1
        for artifact in /etc/acx/gpu-lifecycle.env /etc/tmpfiles.d/acx-gpu.conf \
            /etc/systemd/system/acx-gpu-start.service /etc/systemd/system/acx-gpu-start.timer \
            /etc/systemd/system/acx-gpu-reap.service /etc/systemd/system/acx-gpu-reap.timer \
            /etc/systemd/system/acx-gpu-intent.path; do
            if [ "$artifact" = /etc/systemd/system/acx-gpu-intent.path ] \
                && [ "$intent_path_available" -eq 0 ]; then
                continue
            fi
            sudo cp "$artifact" "$snapshot_stage/${artifact##*/}" || {
                sudo rm -rf "$snapshot_stage"
                return 1
            }
        done
        # mktemp runs as root with mode 0700; allow the deploy shell to expand
        # the file glob before applying modes and publishing the directory.
        if ! sudo chmod 0755 "$snapshot_stage" \
            || ! sudo chmod 0644 "$snapshot_stage/"*; then
            sudo rm -rf "$snapshot_stage"
            return 1
        fi
        snapshot_dir="$snapshot_stage"
    fi
    # Validate staged and historical snapshots before publication or updating
    # previous. Empty artifacts cannot restore the STOP backstop on rollback.
    if ! validate_gpu_lifecycle_snapshot "$snapshot_dir" "$((1 - intent_path_available))"; then
        if [ -n "$snapshot_stage" ]; then
            sudo rm -rf "$snapshot_stage"
        fi
        return 1
    fi
    if [ -n "$snapshot_stage" ]; then
        sudo python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' \
            "$snapshot_stage" "$previous_release/systemd" || {
            sudo rm -rf "$snapshot_stage"
            return 1
        }
    fi
}

lifecycle_transaction_complete=0
unit_stage=''
cleanup_gpu_lifecycle_transaction() {
    local status=$?
    trap - ERR EXIT
    if [ -n "${unit_stage:-}" ]; then
        sudo rm -rf "$unit_stage" "$unit_stage.link" || \
            echo 'warning: could not remove unpublished lifecycle generation' >&2
    fi
    if [ "$status" -ne 0 ] && [ "$lifecycle_transaction_complete" -eq 0 ]; then
        echo 'error: lifecycle transaction failed; running fail-safe STOP path' >&2
        if ! fence_gpu_intent_path; then
            echo 'error: could not fence intent path during cleanup; watcher may remain active' >&2
        fi
        if ! fence_gpu_lifecycle_start; then
            echo 'error: could not fence START during cleanup; reaper not invoked concurrently' >&2
        elif ! sudo systemctl start acx-gpu-reap.service; then
            echo 'error: fail-safe acx-gpu-reap.service invocation failed' >&2
        fi
    fi
    exit "$status"
}

# Hermetic verification entrypoint used by deploy-contract tests. Keeping the
# check in this script means tests execute the same fail-closed code that is
# shipped to and run on the host.
if [ "${1:-}" = "--verify-systemd-only" ]; then
    [ "$#" -eq 1 ] || { echo "error: --verify-systemd-only accepts no arguments" >&2; exit 2; }
    expected_unit_dir="${ACX_EXPECTED_SYSTEMD_DIR:-/etc/systemd/system}"
    verify_gpu_lifecycle_timers \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-start.service" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-start.timer" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-reap.service" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-reap.timer" | awk '{print $1}')" \
        "${ACX_EXPECTED_MAX_LEASE_SECONDS:?ACX_EXPECTED_MAX_LEASE_SECONDS is required}" \
    && verify_gpu_intent_path \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-intent.path" | awk '{print $1}')"
    exit $?
fi

if [ "${1:-}" = "--activate-systemd-only" ]; then
    [ "$#" -eq 1 ] || { echo "error: --activate-systemd-only accepts no arguments" >&2; exit 2; }
    expected_unit_dir="${ACX_EXPECTED_SYSTEMD_DIR:-/etc/systemd/system}"
    trap cleanup_gpu_lifecycle_transaction ERR EXIT
    fence_gpu_intent_path
    fence_gpu_lifecycle_start
    activate_gpu_lifecycle_timers \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-start.service" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-start.timer" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-reap.service" | awk '{print $1}')" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-reap.timer" | awk '{print $1}')" \
        "${ACX_EXPECTED_MAX_LEASE_SECONDS:?ACX_EXPECTED_MAX_LEASE_SECONDS is required}" \
        "$(sha256_file "${expected_unit_dir}/acx-gpu-intent.path" | awk '{print $1}')"
    lifecycle_transaction_complete=1
    trap - ERR EXIT
    exit $?
fi

HOST=""
SSH_USER="${OCI_USER:-ubuntu}"
SSH_USER_EXPLICIT=0
GPU_INSTANCE_NAME="${GPU_INSTANCE_NAME:-acx-gpu-burst}"
GPU_INSTANCE_ID="${GPU_INSTANCE_ID:-}"
MAX_LEASE_SECONDS="${MAX_LEASE_SECONDS:-3600}"
# Only unset operator overrides receive defaults. An explicitly empty value
# remains invalid and reaches the fail-closed validation below.
IDLE_SECONDS="${IDLE_SECONDS-300}"
START_INTERVAL="${START_INTERVAL-30s}"
REAP_INTERVAL="${REAP_INTERVAL-2min}"
READY_URL="${READY_URL-}"
LOAD_STALE_GRACE_SECONDS="${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS:-600}"
REMOTE_COMMAND_TIMEOUT_SECONDS="${REMOTE_COMMAND_TIMEOUT_SECONDS:-180}"
# The API container publishes load and intent dumps as its pinned uid/gid. The
# host lifecycle units need that gid as a supplementary group to read them. systemd
# resolves SupplementaryGroups through NSS, so the gid must also have a *name*.
ACX_API_GID="${ACX_API_GID:-10001}"
ACX_API_GROUP="${ACX_API_GROUP:-acxapi}"
DRY_RUN=0
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DEPLOYMENTS_FILE="${ACX_GPU_DEPLOYMENTS_FILE:-${repo_root}/scripts/deploy/gpu-snapshot-deployments.conf}"

resolve_api_image_gid() {
    local dockerfile=$1 candidates candidate_count
    [ -r "$dockerfile" ] || {
        echo "error: api image Dockerfile is missing or unreadable: $dockerfile" >&2
        return 1
    }
    candidates=$(sed -nE \
        's/^[[:space:]]*RUN[[:space:]]+groupadd[[:space:]]+-r[[:space:]]+-g[[:space:]]+([0-9]+)([[:space:]]|$).*/\1/p' \
        "$dockerfile")
    candidate_count=$(printf '%s\n' "$candidates" | awk 'NF {count++} END {print count + 0}')
    [ "$candidate_count" -eq 1 ] || {
        echo "error: api image Dockerfile must pin exactly one runtime gid with groupadd -r -g; found ${candidate_count}" >&2
        return 1
    }
    [[ "$candidates" =~ ^[0-9]+$ ]] || {
        echo "error: api image Dockerfile runtime gid is not a decimal number: $candidates" >&2
        return 1
    }
    printf '%s\n' "$candidates"
}

ACX_API_IMAGE_GID=$(resolve_api_image_gid "${repo_root}/apps/prototype-description-service/Dockerfile") || exit 2
if [[ ! "$ACX_API_GID" =~ ^[0-9]+$ ]]; then
    echo "error: ACX_API_GID must be a decimal gid matching the api image pinned gid ${ACX_API_IMAGE_GID}; received '${ACX_API_GID}'" >&2
    exit 2
fi
if [ "$ACX_API_GID" != "$ACX_API_IMAGE_GID" ]; then
    echo "error: ACX_API_GID=${ACX_API_GID} disagrees with api image pinned gid=${ACX_API_IMAGE_GID}; refusing deploy" >&2
    exit 2
fi

LOAD_ENVIRONMENTS=""
LOAD_ENVIRONMENT_DIRS=""
TMPFILES_ENVIRONMENT_ENTRIES=""
INTENT_PATH_ENTRIES=""
# The operator-intent contract names exactly these environments. Other
# registered deployments still get load directories, but never path triggers.
GPU_INTENT_ENVIRONMENTS="dev staging prod"

append_deployment() {
    local environment=$1 source=$2
    [[ "$environment" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || {
        echo "error: invalid GPU snapshot deployment '$environment' in $source" >&2
        exit 2
    }
    case " $LOAD_ENVIRONMENTS " in
        *" $environment "*)
            echo "error: duplicate GPU snapshot deployment '$environment' in $source" >&2
            exit 2
            ;;
    esac
    LOAD_ENVIRONMENTS="${LOAD_ENVIRONMENTS:+${LOAD_ENVIRONMENTS} }${environment}"
    LOAD_ENVIRONMENT_DIRS="${LOAD_ENVIRONMENT_DIRS:+${LOAD_ENVIRONMENT_DIRS} }/run/acx-write/${environment}"
    TMPFILES_ENVIRONMENT_ENTRIES="${TMPFILES_ENVIRONMENT_ENTRIES:+${TMPFILES_ENVIRONMENT_ENTRIES}
}d /run/acx-write/${environment} 0775 root ${ACX_API_GID} -"
    case " $GPU_INTENT_ENVIRONMENTS " in
        *" $environment "*)
            INTENT_PATH_ENTRIES="${INTENT_PATH_ENTRIES:+${INTENT_PATH_ENTRIES}
}PathChanged=/run/acx-write/${environment}/gpu-intent.json"
            ;;
    esac
}

load_deployments() {
    local environment line_number=0
    [ -r "$DEPLOYMENTS_FILE" ] || {
        echo "error: GPU snapshot deployments file is missing or unreadable: $DEPLOYMENTS_FILE" >&2
        exit 2
    }
    while IFS= read -r environment || [ -n "$environment" ]; do
        line_number=$((line_number + 1))
        [ -n "$environment" ] || {
            echo "error: empty GPU snapshot deployment at ${DEPLOYMENTS_FILE}:${line_number}" >&2
            exit 2
        }
        append_deployment "$environment" "${DEPLOYMENTS_FILE}:${line_number}"
    done < "$DEPLOYMENTS_FILE"
    [ -n "$LOAD_ENVIRONMENTS" ] || {
        echo "error: GPU snapshot deployment registry is empty: $DEPLOYMENTS_FILE" >&2
        exit 2
    }
}

load_deployments

while [ $# -gt 0 ]; do
    case "$1" in
        --user) SSH_USER="$2"; SSH_USER_EXPLICIT=1; shift 2 ;;
        --host) HOST="$2"; shift 2 ;;
        --instance-id) GPU_INSTANCE_ID="$2"; shift 2 ;;
        --max-lease-seconds) MAX_LEASE_SECONDS="$2"; shift 2 ;;
        --idle-seconds) IDLE_SECONDS="$2"; shift 2 ;;
        --ready-url) READY_URL="$2"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

[ -n "$HOST" ] || { echo "error: --host is required" >&2; exit 2; }

# Keep the historical --host user@host form working for recovery commands, but
# normalize it before any transport call. Pipeline callers always provide the
# identity as separate values.
if [[ "$HOST" == *@* ]]; then
    if [ "$SSH_USER_EXPLICIT" -eq 1 ]; then
        echo "error: --host must not contain a user when --user is provided" >&2
        exit 2
    fi
    SSH_USER="${HOST%%@*}"
    HOST="${HOST#*@}"
fi

assert_safe_ssh_identity() {
    local name=$1 value=$2
    if [ -z "$value" ]; then
        echo "error: ${name} must not be empty" >&2
        exit 2
    fi
    if [[ "$value" == -* ]]; then
        echo "error: ${name} must not start with '-' (ssh option injection): ${value}" >&2
        exit 2
    fi
    if [[ ! "$value" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
        echo "error: ${name} failed charset validation (allowed: [A-Za-z0-9_.:-]+); refusing: ${value}" >&2
        exit 2
    fi
}
assert_safe_ssh_identity "SSH user" "$SSH_USER"
assert_safe_ssh_identity "SSH host" "$HOST"

# Accept a deliberately small, portable subset of systemd monotonic timespans.
# Validate before OCI lookup, transport, or rendering: systemd may merely warn
# about an invalid OnUnitActiveSec and leave a boot-only timer active.
python3 - "$START_INTERVAL" "$REAP_INTERVAL" <<'PY'
import re
import sys

units = {"s": 1, "min": 60, "h": 3600, "d": 86400}
for name, value in zip(("START_INTERVAL", "REAP_INTERVAL"), sys.argv[1:]):
    match = re.fullmatch(r"([1-9][0-9]{0,19})(s|min|h|d)", value)
    if match and int(match[1]) * units[match[2]] * 1_000_000 < 2**64 - 1:
        continue
    sys.exit(f"error: {name} must be a finite positive integer timespan with suffix s, min, h, or d")
PY

# A cap of 0 disables the cost backstop. That is exactly the [RES-07] shape this
# work exists to remove, so refuse it here rather than discover it on a bill.
if [[ ! "$MAX_LEASE_SECONDS" =~ ^[0-9]+$ ]] \
    || ! [ "$MAX_LEASE_SECONDS" -ge 1 ] 2>/dev/null \
    || ! [ "$MAX_LEASE_SECONDS" -le 86400 ] 2>/dev/null; then
    echo "error: --max-lease-seconds must be an integer from 1 through 86400" >&2
    exit 2
fi
if [[ ! "$IDLE_SECONDS" =~ ^[0-9]+$ ]] || ! [ "$IDLE_SECONDS" -gt 0 ] 2>/dev/null; then
    echo "error: IDLE_SECONDS (--idle-seconds) must be a positive integer (> 0)" >&2
    exit 2
fi
if ! [ "$LOAD_STALE_GRACE_SECONDS" -ge 120 ] 2>/dev/null; then
    echo "error: ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS must be an integer >= 120" >&2
    exit 2
fi
if ! [ "$REMOTE_COMMAND_TIMEOUT_SECONDS" -gt 0 ] 2>/dev/null; then
    echo "error: REMOTE_COMMAND_TIMEOUT_SECONDS must be a positive integer (> 0)" >&2
    exit 2
fi
if [ -z "$READY_URL" ]; then
    echo "error: READY_URL (--ready-url) is required; provide the GPU service readiness endpoint" >&2
    exit 2
fi
# Parse the authority instead of accepting any character soup after ``http://``.
# In particular, ``http:///health`` has a scheme and path but no host.
case "$READY_URL" in
    http://*) ready_url_remainder=${READY_URL#http://} ;;
    https://*) ready_url_remainder=${READY_URL#https://} ;;
    *)
        echo "error: READY_URL (--ready-url) must use http or https" >&2
        exit 2
        ;;
esac
ready_url_pattern='^https?://[][A-Za-z0-9._~:/?#%+,={}-]+$'
if [[ ! "$READY_URL" =~ $ready_url_pattern ]]; then
    echo "error: READY_URL (--ready-url) contains whitespace or shell metacharacters" >&2
    exit 2
fi
ready_url_authority=${ready_url_remainder%%[/?#]*}
if [ -z "$ready_url_authority" ] || [[ "$ready_url_authority" == *@* ]]; then
    echo "error: READY_URL (--ready-url) must contain a non-empty hostname without userinfo" >&2
    exit 2
fi
ready_url_port=""
if [[ "$ready_url_authority" =~ ^\[([0-9A-Fa-f:.]+)\](:([0-9]+))?$ ]]; then
    ready_url_hostname=${BASH_REMATCH[1]}
    ready_url_port=${BASH_REMATCH[3]:-}
elif [[ "$ready_url_authority" =~ ^([A-Za-z0-9][A-Za-z0-9.-]*)(:([0-9]+))?$ ]]; then
    ready_url_hostname=${BASH_REMATCH[1]}
    ready_url_port=${BASH_REMATCH[3]:-}
else
    echo "error: READY_URL (--ready-url) has a malformed hostname or port" >&2
    exit 2
fi
if [ -z "$ready_url_hostname" ]; then
    echo "error: READY_URL (--ready-url) must contain a non-empty hostname" >&2
    exit 2
fi
if [ -n "$ready_url_port" ] \
    && { ! [ "$ready_url_port" -ge 1 ] 2>/dev/null \
        || ! [ "$ready_url_port" -le 65535 ] 2>/dev/null; }; then
    echo "error: READY_URL (--ready-url) port must be between 1 and 65535" >&2
    exit 2
fi

# --- resolve the GPU instance OCID -------------------------------------------
# Resolved by display name against OCI rather than pasted, so a stale OCID in a
# unit file cannot silently point the reaper at an instance that no longer
# exists and report a clean exit forever (rg-005).
gpu_instance_id_source="pinned"
if [ -z "$GPU_INSTANCE_ID" ]; then
    gpu_instance_id_source="resolved-by-name"
    command -v oci >/dev/null 2>&1 || {
        echo "error: no --instance-id given and no local oci CLI to resolve '${GPU_INSTANCE_NAME}'" >&2
        exit 2
    }
    tenancy=$(awk -F= '/^tenancy/{gsub(/ /,"");print $2; exit}' "${OCI_CLI_CONFIG_FILE:-$HOME/.oci/config}")
    [ -n "$tenancy" ] || { echo "error: could not read tenancy from the oci config" >&2; exit 2; }
    GPU_INSTANCE_ID=$(oci compute instance list --compartment-id "$tenancy" --all \
        --query "data[?\"display-name\"=='${GPU_INSTANCE_NAME}' && \"lifecycle-state\"!='TERMINATED'].id | [0]" \
        --raw-output 2>/dev/null || true)
    [ -n "$GPU_INSTANCE_ID" ] && [ "$GPU_INSTANCE_ID" != "null" ] || {
        echo "error: could not resolve an instance named '${GPU_INSTANCE_NAME}'" >&2
        exit 2
    }
fi
if [[ ! "$GPU_INSTANCE_ID" =~ ^ocid1\.instance\.oc1\.[a-z0-9-]+\.[a-z0-9]+$ ]]; then
    echo "error: GPU instance OCID must match ocid1.instance.oc1.<region>.<identifier>" >&2
    exit 2
fi
printf -v remote_gpu_instance_id '%q' "$GPU_INSTANCE_ID"
echo "gpu instance: ${GPU_INSTANCE_NAME} (...${GPU_INSTANCE_ID: -12})"
echo "OCID source:  ${gpu_instance_id_source}"
echo "max lease:    ${MAX_LEASE_SECONDS}s   idle: ${IDLE_SECONDS}s"

release_id=$({
    for source_path in "${repo_root}"/infra/oci/gpu_lifecycle/*.py \
        "$DEPLOYMENTS_FILE"; do
        printf '%s %s\n' "${source_path#"${repo_root}/"}" \
            "$(git -C "$repo_root" hash-object "$source_path")"
    done
    printf 'installer %s\n' "$(git -C "$repo_root" hash-object "$0")"
    printf 'instance=%s\nmax=%s\nidle=%s\nready=%s\nstart=%s\nreap=%s\ngrace=%s\ndeployments=%s\n' \
        "$GPU_INSTANCE_ID" "$MAX_LEASE_SECONDS" "$IDLE_SECONDS" "$READY_URL" \
        "$START_INTERVAL" "$REAP_INTERVAL" "$LOAD_STALE_GRACE_SECONDS" "$LOAD_ENVIRONMENTS"
} | git -C "$repo_root" hash-object --stdin)
remote_release="/opt/acx-gpu/releases/${release_id}"
remote_stage="/opt/acx-gpu/releases/.staging-${release_id}"

SSH_OPTIONS=(
    -o BatchMode=yes
    -o ConnectTimeout=10
    -o ServerAliveInterval=15
    -o ServerAliveCountMax=3
)

run_with_deadline() {
    local description=$1
    shift
    # Python provides sessions on Linux and macOS without GNU setsid/timeout.
    # Killing only ssh leaves local descendants holding the captured pipes.
    python3 - "$description" "$REMOTE_COMMAND_TIMEOUT_SECONDS" "$@" <<'PY'
import os
import signal
import subprocess
import sys

description, seconds = sys.argv[1:3]
process = subprocess.Popen(sys.argv[3:], start_new_session=True)
try:
    status = process.wait(timeout=int(seconds))
except subprocess.TimeoutExpired:
    print(f"error: {description} exceeded {seconds}s", file=sys.stderr, flush=True)
    def signal_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
    signal_group(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    finally:
        # Even if the leader exited on TERM, descendants may have ignored it.
        signal_group(signal.SIGKILL)
        process.wait()
    status = 124
sys.exit(status if status >= 0 else 128 - status)
PY
}

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- dry run: would stage release ${release_id} at ${SSH_USER}@${HOST}:${remote_stage}"
    echo "--- dry run: would validate the staged package import"
    echo "--- dry run: would atomically switch /opt/acx-gpu/current -> ${remote_release}"
    echo "--- dry run: would install acx-gpu-start.{service,timer} + acx-gpu-reap.{service,timer} + acx-gpu-intent.path"
    echo "--- dry run: would create host-owned /run/acx and isolated API-writable deployment directories: ${LOAD_ENVIRONMENT_DIRS}"
    echo "ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap --instance-id \${GPU_INSTANCE_ID} --idle-seconds \${IDLE_SECONDS} --max-lease-seconds \${MAX_LEASE_SECONDS} (rendered MAX_LEASE_SECONDS=${MAX_LEASE_SECONDS})"
    echo "--- dry run: would verify systemctl is-enabled + is-active for lifecycle timers and acx-gpu-intent.path"
    exit 0
fi

# --- ship the module ---------------------------------------------------------
# Copied to a dedicated root rather than run from a checkout, so the units do not
# depend on a worktree that a later cleanup may reap. The live `current` link is
# switched only after the content-addressed staged release imports successfully;
# older release directories remain available for rollback.
# Validate the identity at the boundary where remote transport begins.
: "${SSH_USER:?SSH_USER must be set before remote staging}"
run_with_deadline "remote release staging" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
sudo mkdir -p '${remote_stage}/infra/oci/gpu_lifecycle' '${remote_stage}/scripts/deploy' /etc/acx
sudo chown -R ubuntu:ubuntu /opt/acx-gpu
find '${remote_stage}/infra/oci/gpu_lifecycle' -mindepth 1 -maxdepth 1 -delete
touch '${remote_stage}/infra/__init__.py' '${remote_stage}/infra/oci/__init__.py'"
run_with_deadline "GPU lifecycle module copy" \
    scp -q "${SSH_OPTIONS[@]}" -o "User=${SSH_USER}" -- \
        "${repo_root}"/infra/oci/gpu_lifecycle/*.py \
        "${HOST}:${remote_stage}/infra/oci/gpu_lifecycle/"
run_with_deadline "GPU deployment registry copy" \
    scp -q "${SSH_OPTIONS[@]}" -o "User=${SSH_USER}" -- "$DEPLOYMENTS_FILE" \
        "${HOST}:${remote_stage}/scripts/deploy/gpu-snapshot-deployments.conf"
run_with_deadline "remote release validation and switch" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
PYTHONPATH='${remote_stage}' python3 -c 'import infra.oci.gpu_lifecycle.reaper'
if [ -e '${remote_release}' ]; then
    sudo rm -rf '${remote_stage}'
else
    sudo mv '${remote_stage}' '${remote_release}'
fi"

# --- install units -----------------------------------------------------------
sha256_function=$(declare -f sha256_file)
verification_function=$(declare -f verify_gpu_lifecycle_timers)
start_verification_function=$(declare -f verify_gpu_lifecycle_start_timer)
intent_path_verification_function=$(declare -f verify_gpu_intent_path)
intent_path_fence_function=$(declare -f fence_gpu_intent_path)
activation_function=$(declare -f activate_gpu_lifecycle_timers)
load_snapshot_proof_function=$(declare -f load_snapshots_ready_for_reaper_proof)
start_fence_function=$(declare -f fence_gpu_lifecycle_start)
stale_reaper_purge_function=$(declare -f purge_stale_gpu_reaper_units)
api_group_function=$(declare -f ensure_acx_api_group)
cleanup_function=$(declare -f cleanup_gpu_lifecycle_transaction)
snapshot_function=$(declare -f snapshot_gpu_lifecycle_release)
snapshot_validation_function=$(declare -f validate_gpu_lifecycle_snapshot)
run_with_deadline "systemd unit installation" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
${sha256_function}
${verification_function}
${start_verification_function}
${intent_path_verification_function}
${intent_path_fence_function}
${activation_function}
${load_snapshot_proof_function}
${start_fence_function}
${stale_reaper_purge_function}
${api_group_function}
${cleanup_function}
${snapshot_function}
${snapshot_validation_function}
lifecycle_transaction_complete=0
unit_stage=''
trap cleanup_gpu_lifecycle_transaction ERR EXIT

# ARCH-13/COST-04: establish the fail-safe before changing the live release or
# any effective lifecycle artifact. The trap remains armed until the reaper is
# proved and START is re-enabled and verified.
fence_gpu_intent_path
fence_gpu_lifecycle_start
purge_stale_gpu_reaper_units
# The units below name this group; resolve it (creating it if absent) before any
# unit file is written, so no unit can be installed referencing an unresolvable gid.
ACX_API_GROUP_NAME=\$(ensure_acx_api_group '${ACX_API_GID}' '${ACX_API_GROUP}')
previous_release=\$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' /opt/acx-gpu/current)
if [ -n \"\$previous_release\" ] && [ \"\$previous_release\" != '${remote_release}' ] \
    && [ -d \"\$previous_release\" ]; then
    snapshot_gpu_lifecycle_release \"\$previous_release\"
    ln -sfn \"\$previous_release\" '/opt/acx-gpu/.previous-${release_id}'
    sudo python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' '/opt/acx-gpu/.previous-${release_id}' /opt/acx-gpu/previous
fi
ln -sfn '${remote_release}' '/opt/acx-gpu/.current-${release_id}'
# os.replace atomically replaces the symlink itself on both Linux and BSD.
sudo python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' '/opt/acx-gpu/.current-${release_id}' /opt/acx-gpu/current

# Every render, including an idempotent rerun, gets a private generation.
# Never tee into the published rollback snapshot or effective service files.
sudo mkdir -p '${remote_release}'
unit_stage=\$(sudo mktemp -d '${remote_release}/.systemd.XXXXXX')
sudo chmod 0755 \"\$unit_stage\"
sudo tee \"\$unit_stage/gpu-lifecycle.env\" >/dev/null <<ENV
GPU_INSTANCE_ID=${remote_gpu_instance_id}
MAX_LEASE_SECONDS=${MAX_LEASE_SECONDS}
IDLE_SECONDS=${IDLE_SECONDS}
ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS=${LOAD_STALE_GRACE_SECONDS}
READY_URL=${READY_URL}
ENV
sudo chmod 0644 \"\$unit_stage/gpu-lifecycle.env\"

sudo tee \"\$unit_stage/acx-gpu-start.service\" >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU start-on-demand (START when describe work is waiting)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
TimeoutStartSec=1200s
RuntimeMaxSec=1200s
User=ubuntu
SupplementaryGroups=\${ACX_API_GROUP_NAME}
StateDirectory=acx-gpu
StateDirectoryMode=0700
# instance_principal: the VM carries no API key. Requires a dynamic-group grant
# of INSTANCE_POWER_ACTIONS on the GPU compartment, else every run 404s.
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu/current
ExecStart=/usr/bin/flock --wait 120 /var/lib/acx-gpu/lifecycle.lock /usr/bin/python3 -m infra.oci.gpu_lifecycle --mode start --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --intent-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /var/lib/acx-gpu/running-since.json --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci --ready-url \\\${READY_URL}
UNIT

sudo tee \"\$unit_stage/acx-gpu-start.timer\" >/dev/null <<UNIT
[Unit]
Description=Poll describe load and start the burst GPU

[Timer]
# OnActiveSec, not OnBootSec: a boot-relative deadline is already in the past when the
# timer is enabled with --now on a host that has been up longer than it, so systemd fires
# the poll immediately and the settling window is silently skipped on every redeploy.
OnActiveSec=2min
OnUnitActiveSec=${START_INTERVAL}
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

sudo tee \"\$unit_stage/acx-gpu-intent.path\" >/dev/null <<UNIT
[Unit]
Description=Start the ACX burst GPU when an operator intent changes

[Path]
${INTENT_PATH_ENTRIES}
Unit=acx-gpu-start.service

[Install]
WantedBy=paths.target
UNIT

sudo tee \"\$unit_stage/acx-gpu-reap.service\" >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU reaper (STOP on drain; forced STOP at the max lease)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
TimeoutStartSec=1200s
RuntimeMaxSec=1200s
User=ubuntu
SupplementaryGroups=\${ACX_API_GROUP_NAME}
StateDirectory=acx-gpu
StateDirectoryMode=0700
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu/current
ExecStart=/usr/bin/flock --wait 120 /var/lib/acx-gpu/lifecycle.lock /usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --intent-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /var/lib/acx-gpu/running-since.json --idle-seconds \\\${IDLE_SECONDS} --max-lease-seconds \\\${MAX_LEASE_SECONDS} --fence-delay-seconds 2 --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci
UNIT

sudo tee \"\$unit_stage/acx-gpu-reap.timer\" >/dev/null <<UNIT
[Unit]
Description=Run the ACX burst GPU reaper every ${REAP_INTERVAL}

[Timer]
# OnActiveSec for the same reason as the start timer: the first reap must be relative to
# timer activation so a redeploy cannot trigger it before the load snapshot is written.
OnActiveSec=3min
OnUnitActiveSec=${REAP_INTERVAL}
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT

# The host lifecycle units exclusively own the state directory. The API gets
# only a read-only bind mount of it, while the API uid/gid can publish load dumps
# atomically in the separate load directory. SupplementaryGroups lets the
# ubuntu units read the API-owned load dump without granting the API host-side
# write access to lifecycle state.
# systemd resolves the group name in SupplementaryGroups through NSS before
# ExecStart. A bare numeric chown creates no group entry, so both lifecycle
# units died at status=216/GROUP and the burst GPU lost its only stop path. What
# the units need is a resolvable GID, not a particular name, so fall back to a
# second name when the preferred one is already taken at another GID, then
# assert the postcondition under set -e. Asserting on groupadd exit status
# instead would wedge the install permanently on a name collision.
# Editing note: this block is spliced into a double-quoted ssh payload, so a
# literal double quote, dollar sign, backtick or backslash here does not survive
# transport. Parentheses are safe.
if ! getent group ${ACX_API_GID} >/dev/null 2>&1; then
    sudo groupadd -r -g ${ACX_API_GID} acxapi || sudo groupadd -r -g ${ACX_API_GID} acxgid${ACX_API_GID} || true
    getent group ${ACX_API_GID} >/dev/null 2>&1 || { echo 'ERROR gpu-lifecycle: groupadd exited 0 but NSS still does not resolve GID ${ACX_API_GID}; both lifecycle units would die at 216/GROUP before ExecStart. Check nsswitch group sources on the host, then re-run.' >&2; exit 1; }
fi
sudo mkdir -p /run/acx /run/acx-write ${LOAD_ENVIRONMENT_DIRS}
sudo chown ubuntu:ubuntu /run/acx
sudo chmod 0755 /run/acx
sudo chown root:${ACX_API_GID} /run/acx-write
sudo chmod 0775 /run/acx-write
sudo chown root:${ACX_API_GID} ${LOAD_ENVIRONMENT_DIRS}
sudo chmod 0775 ${LOAD_ENVIRONMENT_DIRS}
sudo touch /run/acx/gpu-state.json.lock
sudo chown ubuntu:ubuntu /run/acx/gpu-state.json.lock
sudo chmod 0600 /run/acx/gpu-state.json.lock
# /run is tmpfs: recreate the directory on every boot, or the bind mount comes
# back root-owned and the container-side writer fails silently. Pre-create the
# state lock too, so no process umask decides its ownership or mode.
sudo tee \"\$unit_stage/acx-gpu.conf\" >/dev/null <<'TMPF'
d /run/acx 0755 ubuntu ubuntu -
d /run/acx-write 0775 root ${ACX_API_GID} -
${TMPFILES_ENVIRONMENT_ENTRIES}
f /run/acx/gpu-state.json.lock 0600 ubuntu ubuntu -
TMPF

# Publish only a complete generation. Replacing the symlink is atomic even
# on reruns; the old directory remains immutable for rollback readers.
sudo chmod 0644 \"\$unit_stage/\"*
validate_gpu_lifecycle_snapshot \"\$unit_stage\"
sudo ln -s \"\$unit_stage\" \"\$unit_stage.link\"
sudo python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' \
    \"\$unit_stage.link\" '${remote_release}/systemd'
unit_stage=''

# Install from the release snapshot rather than hashing files after they are
# live. Effective-fragment hashes below therefore compare staged expectations
# with independently installed files.
sudo install -m 0644 '${remote_release}/systemd/gpu-lifecycle.env' /etc/acx/gpu-lifecycle.env
sudo install -m 0644 '${remote_release}/systemd/acx-gpu.conf' /etc/tmpfiles.d/acx-gpu.conf
for unit in acx-gpu-start.service acx-gpu-start.timer acx-gpu-reap.service acx-gpu-reap.timer acx-gpu-intent.path; do
    sudo install -m 0644 \"${remote_release}/systemd/\$unit\" \"/etc/systemd/system/\$unit\"
done
sudo chmod 0644 '${remote_release}/systemd/'*
expected_start_service_hash=\$(sha256_file '${remote_release}/systemd/acx-gpu-start.service' | awk '{print \$1}')
expected_start_timer_hash=\$(sha256_file '${remote_release}/systemd/acx-gpu-start.timer' | awk '{print \$1}')
expected_reap_service_hash=\$(sha256_file '${remote_release}/systemd/acx-gpu-reap.service' | awk '{print \$1}')
expected_reap_timer_hash=\$(sha256_file '${remote_release}/systemd/acx-gpu-reap.timer' | awk '{print \$1}')
expected_intent_path_hash=\$(sha256_file '${remote_release}/systemd/acx-gpu-intent.path' | awk '{print \$1}')

sudo systemctl daemon-reload
activate_gpu_lifecycle_timers \
    \"\$expected_start_service_hash\" \"\$expected_start_timer_hash\" \
    \"\$expected_reap_service_hash\" \"\$expected_reap_timer_hash\" \
    '${MAX_LEASE_SECONDS}' \"\$expected_intent_path_hash\"
lifecycle_transaction_complete=1
trap - ERR EXIT
echo '--- installed timers ---'
if ! systemctl list-timers --all --no-pager | grep acx-gpu; then
    echo 'warning: installed timers were verified but list-timers diagnostic was empty' >&2
fi
"

echo "gpu-lifecycle-install: done"
