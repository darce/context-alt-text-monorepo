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
# Usage (from a laptop, over Tailscale):
#   scripts/deploy/gpu-lifecycle-install.sh --host ubuntu@acx-backend.tail1a44b8.ts.net
# Dry run (print what would change, touch nothing):
#   scripts/deploy/gpu-lifecycle-install.sh --host ... --dry-run

set -euo pipefail

HOST=""
GPU_INSTANCE_NAME="${GPU_INSTANCE_NAME:-acx-gpu-burst}"
GPU_INSTANCE_ID="${GPU_INSTANCE_ID:-}"
MAX_LEASE_SECONDS="${MAX_LEASE_SECONDS:-3600}"
IDLE_SECONDS="${IDLE_SECONDS:-300}"
START_INTERVAL="${START_INTERVAL:-30s}"
REAP_INTERVAL="${REAP_INTERVAL:-2min}"
READY_URL="${READY_URL:-}"
LOAD_STALE_GRACE_SECONDS="${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS:-600}"
DRY_RUN=0

while [ $# -gt 0 ]; do
    case "$1" in
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

# A cap of 0 disables the cost backstop. That is exactly the [RES-07] shape this
# work exists to remove, so refuse it here rather than discover it on a bill.
if ! [ "$MAX_LEASE_SECONDS" -gt 0 ] 2>/dev/null; then
    echo "error: --max-lease-seconds must be > 0; 0 leaves an A10 able to run unbounded" >&2
    exit 2
fi
if ! [ "$LOAD_STALE_GRACE_SECONDS" -ge 120 ] 2>/dev/null; then
    echo "error: ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS must be an integer >= 120" >&2
    exit 2
fi

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

# --- resolve the GPU instance OCID -------------------------------------------
# Resolved by display name against OCI rather than pasted, so a stale OCID in a
# unit file cannot silently point the reaper at an instance that no longer
# exists and report a clean exit forever (rg-005).
if [ -z "$GPU_INSTANCE_ID" ]; then
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
echo "max lease:    ${MAX_LEASE_SECONDS}s   idle: ${IDLE_SECONDS}s"

ready_flag=""
[ -n "$READY_URL" ] && ready_flag="--ready-url ${READY_URL}"

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--- dry run: would sync infra/oci/gpu_lifecycle -> ${HOST}:/opt/acx-gpu/infra/oci/"
    echo "--- dry run: would install acx-gpu-start.{service,timer} + acx-gpu-reap.{service,timer}"
    echo "--- dry run: would create host-owned /run/acx and isolated API-writable /run/acx-write/{dev,staging,prod}"
    exit 0
fi

# --- ship the module ---------------------------------------------------------
# Copied to a dedicated root rather than run from a checkout, so the units do not
# depend on a worktree that a later cleanup may reap.
ssh "$HOST" 'set -eu; sudo mkdir -p /opt/acx-gpu/infra/oci /etc/acx; sudo chown -R ubuntu:ubuntu /opt/acx-gpu'
ssh "$HOST" 'set -eu; rm -rf /opt/acx-gpu/infra/oci/gpu_lifecycle'
scp -q -r "${repo_root}/infra/oci/gpu_lifecycle" "${HOST}:/opt/acx-gpu/infra/oci/gpu_lifecycle"
ssh "$HOST" 'set -eu; touch /opt/acx-gpu/infra/__init__.py /opt/acx-gpu/infra/oci/__init__.py'

# --- install units -----------------------------------------------------------
ssh "$HOST" "set -eu
sudo tee /etc/acx/gpu-lifecycle.env >/dev/null <<ENV
GPU_INSTANCE_ID=${GPU_INSTANCE_ID}
MAX_LEASE_SECONDS=${MAX_LEASE_SECONDS}
IDLE_SECONDS=${IDLE_SECONDS}
ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS=${LOAD_STALE_GRACE_SECONDS}
ENV
sudo chmod 0644 /etc/acx/gpu-lifecycle.env

sudo tee /etc/systemd/system/acx-gpu-start.service >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU start-on-demand (START when describe work is waiting)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
SupplementaryGroups=10001
RuntimeDirectory=acx-gpu
RuntimeDirectoryPreserve=yes
# instance_principal: the VM carries no API key. Requires a dynamic-group grant
# of INSTANCE_POWER_ACTIONS on the GPU compartment, else every run 404s.
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu
ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode start --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /run/acx-gpu/running-since.json --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci ${ready_flag}
UNIT

sudo tee /etc/systemd/system/acx-gpu-start.timer >/dev/null <<UNIT
[Unit]
Description=Poll describe load and start the burst GPU

[Timer]
OnBootSec=2min
OnUnitActiveSec=${START_INTERVAL}
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

sudo tee /etc/systemd/system/acx-gpu-reap.service >/dev/null <<UNIT
[Unit]
Description=ACX burst GPU reaper (STOP on drain; forced STOP at the max lease)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ubuntu
SupplementaryGroups=10001
RuntimeDirectory=acx-gpu
RuntimeDirectoryPreserve=yes
Environment=OCI_CLI_AUTH=instance_principal
EnvironmentFile=/etc/acx/gpu-lifecycle.env
WorkingDirectory=/opt/acx-gpu
ExecStart=/usr/bin/python3 -m infra.oci.gpu_lifecycle --mode reap --instance-id \\\${GPU_INSTANCE_ID} --load-dir /run/acx-write --load-stale-grace-seconds \\\${ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS} --gpu-state-json /run/acx/gpu-state.json --running-since-path /run/acx-gpu/running-since.json --idle-seconds \\\${IDLE_SECONDS} --max-lease-seconds \\\${MAX_LEASE_SECONDS} --fence-delay-seconds 2 --probe-oci --oci-bin /home/ubuntu/.oci-venv/bin/oci
UNIT

sudo tee /etc/systemd/system/acx-gpu-reap.timer >/dev/null <<UNIT
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
sudo mkdir -p /run/acx /run/acx-write /run/acx-write/dev /run/acx-write/staging /run/acx-write/prod
sudo chown ubuntu:ubuntu /run/acx
sudo chmod 0755 /run/acx
sudo chown root:10001 /run/acx-write
sudo chmod 0775 /run/acx-write
sudo chown root:10001 /run/acx-write/dev /run/acx-write/staging /run/acx-write/prod
sudo chmod 0775 /run/acx-write/dev /run/acx-write/staging /run/acx-write/prod
sudo touch /run/acx/gpu-state.json.lock
sudo chown ubuntu:ubuntu /run/acx/gpu-state.json.lock
sudo chmod 0600 /run/acx/gpu-state.json.lock
# /run is tmpfs: recreate the directory on every boot, or the bind mount comes
# back root-owned and the container-side writer fails silently. Pre-create the
# state lock too, so no process umask decides its ownership or mode.
sudo tee /etc/tmpfiles.d/acx-gpu.conf >/dev/null <<'TMPF'
d /run/acx 0755 ubuntu ubuntu -
d /run/acx-write 0775 root 10001 -
d /run/acx-write/dev 0775 root 10001 -
d /run/acx-write/staging 0775 root 10001 -
d /run/acx-write/prod 0775 root 10001 -
f /run/acx/gpu-state.json.lock 0600 ubuntu ubuntu -
TMPF

sudo systemctl daemon-reload
sudo systemctl enable --now acx-gpu-reap.timer
sudo systemctl enable --now acx-gpu-start.timer
echo '--- installed timers ---'
systemctl list-timers --all --no-pager | grep acx-gpu || true
"

echo "gpu-lifecycle-install: done"
