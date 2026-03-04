#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/retry-apply.log}"
TFVARS_FILE="${TFVARS_FILE:-terraform.tfvars}"
INTERVAL="${1:-${RETRY_INTERVAL:-60}}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-0}"

ADS=("saEG:US-ASHBURN-AD-1" "saEG:US-ASHBURN-AD-2" "saEG:US-ASHBURN-AD-3")
if [[ -n "${ADS_CSV:-}" ]]; then
  IFS=',' read -r -a ADS <<< "$ADS_CSV"
fi

if [[ ! -f "$TFVARS_FILE" ]]; then
  echo "Missing $TFVARS_FILE. Create it from terraform.tfvars.example first."
  exit 1
fi

touch "$LOG_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

notify() {
  osascript -e "display notification \"$1\" with title \"OCI Retry Apply\"" 2>/dev/null || true
}

attempt=0
while true; do
  for ad in "${ADS[@]}"; do
    attempt=$((attempt + 1))
    log "Attempt ${attempt}: availability_domain=${ad}"

    tmp_log="$(mktemp "${TMPDIR:-/tmp}/acx-oci-apply.XXXXXX.log")"

    if terraform apply \
      -auto-approve \
      -var-file="$TFVARS_FILE" \
      -var "availability_domain=$ad" >"$tmp_log" 2>&1; then
      cat "$tmp_log" >> "$LOG_FILE"
      rm -f "$tmp_log"
      log "SUCCESS: Terraform apply completed in ${ad}"
      notify "ACX OCI apply succeeded in ${ad}"
      exit 0
    fi

    cat "$tmp_log" >> "$LOG_FILE"

    if ! grep -q "Out of host capacity" "$tmp_log"; then
      rm -f "$tmp_log"
      log "FATAL: Non-capacity error. Aborting retry loop."
      notify "ACX OCI apply failed (non-capacity error)"
      exit 1
    fi

    rm -f "$tmp_log"

    if [[ "$MAX_ATTEMPTS" -gt 0 && "$attempt" -ge "$MAX_ATTEMPTS" ]]; then
      log "Reached MAX_ATTEMPTS=${MAX_ATTEMPTS}. Aborting."
      notify "ACX OCI apply exhausted attempts"
      exit 1
    fi

    log "Capacity unavailable in ${ad}. Retrying in ${INTERVAL}s."
    sleep "$INTERVAL"
  done
done
