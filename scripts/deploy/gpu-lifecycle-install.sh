#!/usr/bin/env bash
# Install the burst-GPU lifecycle controller on acx-backend (GPUW-1).
#
# Why this exists rather than cloud-init: infra/oci/cloud-init.yaml already
# carries a reaper unit, but cloud-init runs once at first boot and acx-backend
# is long past that -- so the units were never installed on the live host.
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

verify_gpu_lifecycle_timers() {
    [ "$#" -eq 5 ] || {
        echo "error: effective-unit verification requires four expected hashes and max lease" >&2
        return 2
    }
    local expected_start_service_hash=$1 expected_start_timer_hash=$2
    local expected_reap_service_hash=$3 expected_reap_timer_hash=$4
    local expected_max_lease=$5 effective_unit_dir expected_env_file
    local unit expected_hash fragment_path drop_in_paths effective_hash exec_start timer
    effective_unit_dir="${ACX_EFFECTIVE_SYSTEMD_DIR:-/etc/systemd/system}"
    expected_env_file="${ACX_EXPECTED_ENV_FILE:-/etc/acx/gpu-lifecycle.env}"

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
        effective_hash=$(sha256sum "$fragment_path" | awk '{print $1}') || {
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

    for timer in acx-gpu-start.timer acx-gpu-reap.timer; do
        systemctl is-enabled --quiet "$timer" || {
            echo "error: $timer is not enabled" >&2
            return 1
        }
        systemctl is-active --quiet "$timer" || {
            echo "error: $timer is not active" >&2
            return 1
        }
        echo "$timer enabled active"
    done
}

# Hermetic verification entrypoint used by deploy-contract tests. Keeping the
# check in this script means tests execute the same fail-closed code that is
# shipped to and run on the host.
if [ "${1:-}" = "--verify-systemd-only" ]; then
    [ "$#" -eq 1 ] || { echo "error: --verify-systemd-only accepts no arguments" >&2; exit 2; }
    expected_unit_dir="${ACX_EXPECTED_SYSTEMD_DIR:-/etc/systemd/system}"
    verify_gpu_lifecycle_timers \
        "$(sha256sum "${expected_unit_dir}/acx-gpu-start.service" | awk '{print $1}')" \
        "$(sha256sum "${expected_unit_dir}/acx-gpu-start.timer" | awk '{print $1}')" \
        "$(sha256sum "${expected_unit_dir}/acx-gpu-reap.service" | awk '{print $1}')" \
        "$(sha256sum "${expected_unit_dir}/acx-gpu-reap.timer" | awk '{print $1}')" \
        "${ACX_EXPECTED_MAX_LEASE_SECONDS:?ACX_EXPECTED_MAX_LEASE_SECONDS is required}"
    exit $?
fi

HOST=""
SSH_USER="${OCI_USER:-ubuntu}"
SSH_USER_EXPLICIT=0
GPU_INSTANCE_NAME="${GPU_INSTANCE_NAME:-acx-gpu-burst}"
GPU_INSTANCE_ID="${GPU_INSTANCE_ID:-}"
MAX_LEASE_SECONDS="${MAX_LEASE_SECONDS:-3600}"
IDLE_SECONDS="${IDLE_SECONDS-300}"
START_INTERVAL="${START_INTERVAL:-30s}"
REAP_INTERVAL="${REAP_INTERVAL:-2min}"
READY_URL="${READY_URL-}"
LOAD_STALE_GRACE_SECONDS="${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS:-600}"
REMOTE_COMMAND_TIMEOUT_SECONDS="${REMOTE_COMMAND_TIMEOUT_SECONDS:-180}"
DRY_RUN=0
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
DEPLOYMENTS_FILE="${ACX_GPU_DEPLOYMENTS_FILE:-${repo_root}/scripts/deploy/gpu-snapshot-deployments.conf}"
LOAD_ENVIRONMENTS=""
LOAD_ENVIRONMENT_DIRS=""
TMPFILES_ENVIRONMENT_ENTRIES=""

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
}d /run/acx-write/${environment} 0775 root 10001 -"
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

# A cap of 0 disables the cost backstop. That is exactly the [RES-07] shape this
# work exists to remove, so refuse it here rather than discover it on a bill.
if ! [ "$MAX_LEASE_SECONDS" -gt 0 ] 2>/dev/null; then
    echo "error: --max-lease-seconds must be > 0; 0 leaves an A10 able to run unbounded" >&2
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
echo "gpu instance: ${GPU_INSTANCE_NAME} (...${GPU_INSTANCE_ID: -12})"
echo "OCID source:  ${gpu_instance_id_source}"
echo "max lease:    ${MAX_LEASE_SECONDS}s   idle: ${IDLE_SECONDS}s"

release_id=$({
    for source_path in "${repo_root}"/infra/oci/gpu_lifecycle/*.py; do
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
    local description=$1 process_id sleep_id="" status timer_id
    shift
    "$@" &
    process_id=$!
    (
        trap 'kill "$sleep_id" 2>/dev/null || true; exit 0' TERM INT
        sleep "$REMOTE_COMMAND_TIMEOUT_SECONDS" &
        sleep_id=$!
        wait "$sleep_id"
        echo "error: ${description} exceeded ${REMOTE_COMMAND_TIMEOUT_SECONDS}s" >&2
        kill -TERM "$process_id" 2>/dev/null || true
        sleep 5
        kill -KILL "$process_id" 2>/dev/null || true
    ) &
    timer_id=$!
    if wait "$process_id"; then
        status=0
    else
        status=$?
    fi
    kill -TERM "$timer_id" 2>/dev/null || true
    wait "$timer_id" 2>/dev/null || true
    return "$status"
}

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- dry run: would stage release ${release_id} at ${SSH_USER}@${HOST}:${remote_stage}"
    echo "--- dry run: would validate the staged package import"
    echo "--- dry run: would atomically switch /opt/acx-gpu/current -> ${remote_release}"
    echo "--- dry run: would install acx-gpu-start.{service,timer} + acx-gpu-reap.{service,timer}"
    echo "--- dry run: would create host-owned /run/acx and isolated API-writable deployment directories: ${LOAD_ENVIRONMENT_DIRS}"
    echo "ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap --instance-id \${GPU_INSTANCE_ID} --idle-seconds \${IDLE_SECONDS} --max-lease-seconds \${MAX_LEASE_SECONDS} (rendered MAX_LEASE_SECONDS=${MAX_LEASE_SECONDS})"
    echo "--- dry run: would verify systemctl is-enabled + is-active for acx-gpu-start.timer and acx-gpu-reap.timer"
    exit 0
fi

# --- ship the module ---------------------------------------------------------
# Copied to a dedicated root rather than run from a checkout, so the units do not
# depend on a worktree that a later cleanup may reap. The live `current` link is
# switched only after the content-addressed staged release imports successfully;
# older release directories remain available for rollback.
run_with_deadline "remote release staging" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
sudo mkdir -p '${remote_stage}/infra/oci/gpu_lifecycle' /etc/acx
sudo chown -R ubuntu:ubuntu /opt/acx-gpu
find '${remote_stage}/infra/oci/gpu_lifecycle' -mindepth 1 -maxdepth 1 -delete
touch '${remote_stage}/infra/__init__.py' '${remote_stage}/infra/oci/__init__.py'"
run_with_deadline "GPU lifecycle module copy" \
    scp -q "${SSH_OPTIONS[@]}" -o "User=${SSH_USER}" -- \
        "${repo_root}"/infra/oci/gpu_lifecycle/*.py \
        "${HOST}:${remote_stage}/infra/oci/gpu_lifecycle/"
run_with_deadline "remote release validation and switch" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
PYTHONPATH='${remote_stage}' python3 -c 'import infra.oci.gpu_lifecycle.reaper'
if [ -e '${remote_release}' ]; then
    sudo rm -rf '${remote_stage}'
else
    sudo mv '${remote_stage}' '${remote_release}'
fi
previous_release=\$(readlink -f /opt/acx-gpu/current 2>/dev/null || true)
if [ -n "\$previous_release" ] && [ "\$previous_release" != '${remote_release}' ] \
    && [ -d "\$previous_release" ]; then
    # Upgrade older releases into rollback-capable generations before changing
    # the live symlink. Never overwrite an existing release snapshot.
    if [ ! -d "\$previous_release/systemd" ]; then
        sudo mkdir -p "\$previous_release/systemd"
        sudo cp /etc/acx/gpu-lifecycle.env "\$previous_release/systemd/gpu-lifecycle.env"
        sudo cp /etc/tmpfiles.d/acx-gpu.conf "\$previous_release/systemd/acx-gpu.conf"
        for unit in acx-gpu-start.service acx-gpu-start.timer acx-gpu-reap.service acx-gpu-reap.timer; do
            sudo cp "/etc/systemd/system/\$unit" "\$previous_release/systemd/\$unit"
        done
        sudo chmod 0644 "\$previous_release/systemd/"*
    fi
    ln -sfn "\$previous_release" '/opt/acx-gpu/.previous-${release_id}'
    sudo mv -Tf '/opt/acx-gpu/.previous-${release_id}' /opt/acx-gpu/previous
fi
ln -sfn '${remote_release}' '/opt/acx-gpu/.current-${release_id}'
sudo mv -Tf '/opt/acx-gpu/.current-${release_id}' /opt/acx-gpu/current"

# --- install units -----------------------------------------------------------
verification_function=$(declare -f verify_gpu_lifecycle_timers)
run_with_deadline "systemd unit installation" \
    ssh "${SSH_OPTIONS[@]}" -l "$SSH_USER" -- "$HOST" "set -euo pipefail
${verification_function}
start_timer_armed=0
cleanup_unverified_start_timer() {
    status=\$?
    if [ "\$status" -ne 0 ] && [ "\$start_timer_armed" -eq 1 ]; then
        echo 'error: lifecycle verification failed; disabling acx-gpu-start.timer' >&2
        if ! sudo systemctl disable --now acx-gpu-start.timer; then
            echo 'error: failed to disable acx-gpu-start.timer during cleanup' >&2
        fi
    fi
    exit "\$status"
}
trap cleanup_unverified_start_timer EXIT
sudo mkdir -p '${remote_release}/systemd'
sudo tee '${remote_release}/systemd/gpu-lifecycle.env' >/dev/null <<ENV
GPU_INSTANCE_ID=${GPU_INSTANCE_ID}
MAX_LEASE_SECONDS=${MAX_LEASE_SECONDS}
IDLE_SECONDS=${IDLE_SECONDS}
ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS=${LOAD_STALE_GRACE_SECONDS}
READY_URL=${READY_URL}
ENV
sudo chmod 0644 '${remote_release}/systemd/gpu-lifecycle.env'

sudo tee /etc/systemd/system/acx-gpu-start.service \
    '${remote_release}/systemd/acx-gpu-start.service' >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU start-on-demand (START when describe work is waiting)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
TimeoutStartSec=1200s
RuntimeMaxSec=1200s
User=ubuntu
SupplementaryGroups=10001
RuntimeDirectory=acx-gpu
RuntimeDirectoryPreserve=yes
# instance_principal: the VM carries no API key. Requires a dynamic-group grant
# of INSTANCE_POWER_ACTIONS on the GPU compartment, else every run 404s.
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu/current
ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode start --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /run/acx-gpu/running-since.json --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci --ready-url \\\${READY_URL}
UNIT

sudo tee /etc/systemd/system/acx-gpu-start.timer \
    '${remote_release}/systemd/acx-gpu-start.timer' >/dev/null <<UNIT
[Unit]
Description=Poll describe load and start the burst GPU

[Timer]
OnBootSec=2min
OnUnitActiveSec=${START_INTERVAL}
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

sudo tee /etc/systemd/system/acx-gpu-reap.service \
    '${remote_release}/systemd/acx-gpu-reap.service' >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU reaper (STOP on drain; forced STOP at the max lease)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
TimeoutStartSec=1200s
RuntimeMaxSec=1200s
User=ubuntu
SupplementaryGroups=10001
RuntimeDirectory=acx-gpu
RuntimeDirectoryPreserve=yes
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu/current
ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /run/acx-gpu/running-since.json --idle-seconds \\\${IDLE_SECONDS} --max-lease-seconds \\\${MAX_LEASE_SECONDS} --fence-delay-seconds 2 --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci
UNIT

sudo tee /etc/systemd/system/acx-gpu-reap.timer \
    '${remote_release}/systemd/acx-gpu-reap.timer' >/dev/null <<UNIT
[Unit]
Description=Run the ACX burst GPU reaper every ${REAP_INTERVAL}

[Timer]
OnBootSec=3min
OnUnitActiveSec=${REAP_INTERVAL}
AccuracySec=10s

[Install]
WantedBy=timers.target
UNIT

# The host lifecycle units exclusively own the state directory. The API gets
# only a read-only bind mount of it, while uid/gid 10001 can publish load dumps
# atomically in the separate load directory. SupplementaryGroups=10001 lets the
# ubuntu units read the API-owned load dump without granting the API host-side
# write access to lifecycle state.
sudo mkdir -p /run/acx /run/acx-write ${LOAD_ENVIRONMENT_DIRS}
sudo chown ubuntu:ubuntu /run/acx
sudo chmod 0755 /run/acx
sudo chown root:10001 /run/acx-write
sudo chmod 0775 /run/acx-write
sudo chown root:10001 ${LOAD_ENVIRONMENT_DIRS}
sudo chmod 0775 ${LOAD_ENVIRONMENT_DIRS}
sudo touch /run/acx/gpu-state.json.lock
sudo chown ubuntu:ubuntu /run/acx/gpu-state.json.lock
sudo chmod 0600 /run/acx/gpu-state.json.lock
# /run is tmpfs: recreate the directory on every boot, or the bind mount comes
# back root-owned and the container-side writer fails silently. Pre-create the
# state lock too, so no process umask decides its ownership or mode.
sudo tee '${remote_release}/systemd/acx-gpu.conf' >/dev/null <<'TMPF'
d /run/acx 0755 ubuntu ubuntu -
d /run/acx-write 0775 root 10001 -
${TMPFILES_ENVIRONMENT_ENTRIES}
f /run/acx/gpu-state.json.lock 0600 ubuntu ubuntu -
TMPF

# Install from the release snapshot rather than hashing files after they are
# live. Effective-fragment hashes below therefore compare staged expectations
# with independently installed files.
sudo install -m 0644 '${remote_release}/systemd/gpu-lifecycle.env' /etc/acx/gpu-lifecycle.env
sudo install -m 0644 '${remote_release}/systemd/acx-gpu.conf' /etc/tmpfiles.d/acx-gpu.conf
for unit in acx-gpu-start.service acx-gpu-start.timer acx-gpu-reap.service acx-gpu-reap.timer; do
    sudo install -m 0644 "${remote_release}/systemd/\$unit" "/etc/systemd/system/\$unit"
done
sudo chmod 0644 '${remote_release}/systemd/'*
expected_start_service_hash=\$(sha256sum '${remote_release}/systemd/acx-gpu-start.service' | awk '{print \$1}')
expected_start_timer_hash=\$(sha256sum '${remote_release}/systemd/acx-gpu-start.timer' | awk '{print \$1}')
expected_reap_service_hash=\$(sha256sum '${remote_release}/systemd/acx-gpu-reap.service' | awk '{print \$1}')
expected_reap_timer_hash=\$(sha256sum '${remote_release}/systemd/acx-gpu-reap.timer' | awk '{print \$1}')

sudo systemctl daemon-reload
sudo systemctl enable --now acx-gpu-reap.timer
# Prove the cost backstop synchronously before scheduling anything capable of
# starting the GPU. acx-gpu-reap.service can only observe or STOP an instance.
sudo systemctl start acx-gpu-reap.service
start_timer_armed=1
sudo systemctl enable --now acx-gpu-start.timer
verify_gpu_lifecycle_timers \
    "\$expected_start_service_hash" "\$expected_start_timer_hash" \
    "\$expected_reap_service_hash" "\$expected_reap_timer_hash" \
    '${MAX_LEASE_SECONDS}'
echo '--- installed timers ---'
if ! systemctl list-timers --all --no-pager | grep acx-gpu; then
    echo 'warning: installed timers were verified but list-timers diagnostic was empty' >&2
fi
start_timer_armed=0
trap - EXIT
"

echo "gpu-lifecycle-install: done"
