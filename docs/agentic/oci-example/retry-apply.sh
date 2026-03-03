#!/usr/bin/env bash
# Retry terraform apply until capacity is available
# OCI Always Free A1.Flex instances are in high demand
# This script cycles through all 3 availability domains
#
# Usage: ./retry-apply.sh [interval_seconds]
#   Runs in background, logs to retry-apply.log, notifies on success.
# Default interval: 60 seconds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="${SCRIPT_DIR}/retry-apply.log"
INTERVAL=${1:-60}
ADS=("saEG:US-ASHBURN-AD-1" "saEG:US-ASHBURN-AD-2" "saEG:US-ASHBURN-AD-3")
MAX_ATTEMPTS=16640

# --- background wrapper ---
if [[ "${__RETRY_BG:-}" != "1" ]]; then
  export __RETRY_BG=1
  echo "Launching retry loop in background (pid logged to retry-apply.log)"
  echo "  Log:  tail -f ${LOG}"
  echo "  Stop: kill \$(head -1 ${LOG})"
  nohup "$0" "$@" > /dev/null 2>&1 &
  disown
  exit 0
fi

cd "$SCRIPT_DIR"

# Write PID as first line so user can kill easily
echo $$ > "$LOG"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

notify() {
  # macOS notification + terminal bell
  osascript -e "display notification \"$1\" with title \"OCI Deploy\"" 2>/dev/null || true
  printf '\a'  # bell
}

ATTEMPT=0
log "Starting retry loop — interval=${INTERVAL}s, max=${MAX_ATTEMPTS}"

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
  for AD in "${ADS[@]}"; do
    ATTEMPT=$((ATTEMPT + 1))
    AD_NUM="${AD##*-}"

    log "Attempt ${ATTEMPT}/${MAX_ATTEMPTS} — AD-${AD_NUM}"

    sed -i.bak "s/availability_domain = \"saEG:US-ASHBURN-AD-[0-9]\"/availability_domain = \"${AD}\"/" main.tf

    if terraform apply -var-file=terraform.tfvars -auto-approve >> "$LOG" 2>&1; then
      log "========================================="
      log "  SUCCESS — instance created in AD-${AD_NUM}"
      log "========================================="
      terraform output >> "$LOG" 2>&1
      notify "Instance created in AD-${AD_NUM}! Check retry-apply.log"
      exit 0
    fi

    if ! grep -q "Out of host capacity" "$LOG"; then
      log "ERROR: Non-capacity error. Stopping."
      notify "Deploy FAILED — non-capacity error. Check retry-apply.log"
      exit 1
    fi

    log "Out of capacity AD-${AD_NUM}. Sleeping ${INTERVAL}s..."
    sleep "$INTERVAL"
  done
done

log "Max attempts reached."
notify "Deploy gave up after ${MAX_ATTEMPTS} attempts"
exit 1
