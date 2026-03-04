#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="${LOG_FILE:-$SCRIPT_DIR/retry-apply.log}"
TFVARS_FILE="${TFVARS_FILE:-terraform.tfvars}"
BASE_INTERVAL="${1:-${RETRY_INTERVAL:-300}}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-0}"
MAX_RETRY_INTERVAL="${MAX_RETRY_INTERVAL:-1800}"
JITTER_MAX="${JITTER_MAX:-30}"
THROTTLE_MIN_WAIT="${THROTTLE_MIN_WAIT:-300}"
APPLY_TIMEOUT_SEC="${APPLY_TIMEOUT_SEC:-900}"
# Optional webhook URL for remote notifications (e.g. Slack, Discord, ntfy.sh)
# Set NOTIFY_WEBHOOK_URL and optionally NOTIFY_WEBHOOK_BODY_TPL (printf template, %s=message)
NOTIFY_WEBHOOK_URL="${NOTIFY_WEBHOOK_URL:-}"
NOTIFY_WEBHOOK_BODY_TPL="${NOTIFY_WEBHOOK_BODY_TPL:-}"

ADS=("saEG:US-ASHBURN-AD-1" "saEG:US-ASHBURN-AD-2" "saEG:US-ASHBURN-AD-3")
if [[ -n "${ADS_CSV:-}" ]]; then
  IFS=',' read -r -a ADS <<< "$ADS_CSV"
fi

if [[ ! -f "$TFVARS_FILE" ]]; then
  echo "Missing $TFVARS_FILE. Create it from terraform.tfvars.example first."
  exit 1
fi

touch "$LOG_FILE"

# ---------------------------------------------------------------------------
# Cron safety: ensure only one instance of this script runs at a time.
# When invoked from cron, a previous apply may still be in flight. We use
# a lock file so the cron job silently exits rather than forking a second run.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Cleanup: kill child processes (terraform), remove temp files and lock on exit.
# Ensures we don't leave stale terraform processes holding the state lock or
# orphaned lock directories preventing future runs.
# ---------------------------------------------------------------------------
_cleanup() {
  # Kill any child terraform processes still holding the state lock.
  local children
  children="$(jobs -p 2>/dev/null)" || true
  if [[ -n "$children" ]]; then
    # shellcheck disable=SC2086
    kill $children 2>/dev/null || true
    wait $children 2>/dev/null || true
  fi
  # Also kill any terraform apply spawned by this script's process group.
  pkill -P $$ 2>/dev/null || true
  # Remove temp log if it still exists.
  rm -f "${_CURRENT_TMP_LOG:-}" 2>/dev/null || true
}

LOCK_FILE="${SCRIPT_DIR}/.retry-apply.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Another retry-apply.sh is already running (lock held via flock). Exiting." | tee -a "$LOG_FILE"
    exit 0
  fi
  trap '_cleanup' EXIT INT TERM
else
  # Portable fallback for environments without flock (common on macOS).
  LOCK_DIR="${SCRIPT_DIR}/.retry-apply.lock.d"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Another retry-apply.sh is already running (lock directory exists). Exiting." | tee -a "$LOG_FILE"
    exit 0
  fi
  trap '_cleanup; rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT INT TERM
fi

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

warn() {
  log "WARN: $*"
}

# ---------------------------------------------------------------------------
# Notifications: macOS + optional webhook (Slack/Discord/ntfy/generic)
# ---------------------------------------------------------------------------
notify() {
  local msg="$1"
  osascript -e "display notification \"$msg\" with title \"OCI Retry Apply\"" 2>/dev/null || true

  if [[ -n "$NOTIFY_WEBHOOK_URL" ]]; then
    local body
    if [[ -n "$NOTIFY_WEBHOOK_BODY_TPL" ]]; then
      # shellcheck disable=SC2059
      body="$(printf "$NOTIFY_WEBHOOK_BODY_TPL" "$msg")"
    else
      # Default: ntfy.sh / generic plain-text POST
      body="$msg"
    fi
    curl -sf -X POST "$NOTIFY_WEBHOOK_URL" \
      -H "Content-Type: text/plain" \
      --data-raw "$body" >/dev/null 2>&1 || true
  fi
}

# ---------------------------------------------------------------------------
# Extract Retry-After header value from terraform output, if present
# ---------------------------------------------------------------------------
extract_retry_after() {
  local file="$1"
  local retry_after

  retry_after="$(grep -Eio 'Retry-After[^0-9]*[0-9]+' "$file" | tail -n 1 | grep -Eo '[0-9]+' || true)"
  if [[ "$retry_after" =~ ^[0-9]+$ ]]; then
    echo "$retry_after"
  fi
}

# ---------------------------------------------------------------------------
# Detect a usable timeout binary (GNU coreutils or macOS gtimeout via brew)
# ---------------------------------------------------------------------------
detect_timeout_bin() {
  if command -v timeout >/dev/null 2>&1; then
    echo "timeout"
    return
  fi
  if command -v gtimeout >/dev/null 2>&1; then
    echo "gtimeout"
    return
  fi
  echo ""
}

# ---------------------------------------------------------------------------
# Classify why the apply failed so we can decide whether to retry.
#
# Returns one of: capacity | limit_exceeded | throttle | timeout | transient | ""
#   ""             -> non-retryable; abort the loop
#   capacity       -> "Out of host capacity"; retry (expected for Always Free ARM)
#   limit_exceeded -> already have the max instances; stop gracefully
#   throttle       -> 429 / rate-limit; retry with a longer wait
#   timeout        -> apply exceeded APPLY_TIMEOUT_SEC; retry
#   transient      -> temporary OCI control-plane error; retry
# ---------------------------------------------------------------------------
retry_reason_for() {
  local exit_code="$1"
  local file="$2"

  # Check LimitExceeded first -- this means we already have the instance.
  if grep -Eqi '(LimitExceeded|service limits were exceeded)' "$file"; then
    echo "limit_exceeded"
    return 0
  fi
  if grep -Eqi 'Out of host capacity' "$file"; then
    echo "capacity"
    return 0
  fi
  if grep -Eqi '(TooManyRequests|429|rate[ -]?limit|throttl)' "$file"; then
    echo "throttle"
    return 0
  fi
  if [[ "$exit_code" -eq 124 || "$exit_code" -eq 137 ]]; then
    echo "timeout"
    return 0
  fi
  if grep -Eqi '(context deadline exceeded|Request canceled|temporar(y|ily) unavailable|Plugin did not respond|problem occurred while preparing the instance)' "$file"; then
    echo "transient"
    return 0
  fi

  echo ""
}

# ---------------------------------------------------------------------------
# Calculate how long to sleep before the next attempt, applying exponential
# backoff (for capacity/transient/timeout) and a floor for throttle errors.
# ---------------------------------------------------------------------------
compute_sleep_seconds() {
  local reason="$1"
  local streak="$2"
  local file="$3"
  local base="$BASE_INTERVAL"
  local retry_after=0
  local capped_streak="$streak"

  if [[ "$reason" == "throttle" ]]; then
    if (( THROTTLE_MIN_WAIT > base )); then
      base="$THROTTLE_MIN_WAIT"
    fi
    retry_after="$(extract_retry_after "$file")"
    if [[ -n "$retry_after" ]] && (( retry_after > base )); then
      base="$retry_after"
    fi
  else
    if (( capped_streak > 8 )); then
      capped_streak=8
    fi
    base=$((base * (1 << (capped_streak - 1))))
  fi

  if (( base > MAX_RETRY_INTERVAL )); then
    base="$MAX_RETRY_INTERVAL"
  fi

  local jitter=0
  if (( JITTER_MAX > 0 )); then
    jitter=$((RANDOM % (JITTER_MAX + 1)))
  fi

  echo $((base + jitter))
}

# ---------------------------------------------------------------------------
# Pre-flight: check if the target instance already exists in terraform state
# or in the live OCI inventory. If so, emit outputs and exit cleanly.
# This mirrors hitrov's ListInstances guard and prevents duplicate resource
# creation errors when the state file is out of sync.
# ---------------------------------------------------------------------------
preflight_check() {
  # 1. Terraform state contains the instance resource
  if terraform state list 2>/dev/null | grep -q 'oci_core_instance\.acx_backend'; then
    log "PREFLIGHT: oci_core_instance.acx_backend already exists in terraform state."
    log "Running 'terraform output' to confirm live state."
    terraform output 2>&1 | tee -a "$LOG_FILE"
    notify "ACX backend already provisioned -- check terraform output for details."
    exit 0
  fi

  # 2. OCI CLI guard: look for a running/provisioning instance tagged project=acx
  #    (Only runs if OCI CLI is available and compartment_ocid is readable from tfvars.)
  if command -v oci >/dev/null 2>&1; then
    local compartment_ocid
    compartment_ocid="$(grep -Eo 'compartment_ocid\s*=\s*"[^"]+"' "$TFVARS_FILE" | grep -Eo '"[^"]+"' | tr -d '"' || true)"
    if [[ -n "$compartment_ocid" ]]; then
      local existing_count
      existing_count="$(
        oci compute instance list \
          --compartment-id "$compartment_ocid" \
          --lifecycle-state RUNNING \
          --query 'length(data[?"freeform-tags".project=='"'"'acx'"'"'])' \
          --raw-output 2>/dev/null || echo "0"
      )"
      if [[ "$existing_count" =~ ^[1-9] ]]; then
        log "PREFLIGHT: Found ${existing_count} running ACX instance(s) in OCI (lifecycle-state=RUNNING, project=acx tag)."
        log "If this is unexpected, run 'terraform import' or 'terraform refresh' to reconcile state."
        notify "ACX backend already running in OCI (${existing_count} instance(s)) -- skipping apply."
        exit 0
      fi
    fi
  fi
}

limit_exceeded_is_safe_success() {
  # Terraform state already has target instance resource.
  if terraform state list 2>/dev/null | grep -q 'oci_core_instance\.acx_backend'; then
    return 0
  fi

  # If OCI CLI is unavailable or compartment cannot be read, we cannot verify success.
  if ! command -v oci >/dev/null 2>&1; then
    return 1
  fi

  local compartment_ocid
  compartment_ocid="$(grep -Eo 'compartment_ocid\s*=\s*"[^"]+"' "$TFVARS_FILE" | grep -Eo '"[^"]+"' | tr -d '"' || true)"
  if [[ -z "$compartment_ocid" ]]; then
    return 1
  fi

  local running_count provisioning_count
  running_count="$(
    oci compute instance list \
      --compartment-id "$compartment_ocid" \
      --lifecycle-state RUNNING \
      --query 'length(data[?"freeform-tags".project=='"'"'acx'"'"'])' \
      --raw-output 2>/dev/null || echo "0"
  )"
  provisioning_count="$(
    oci compute instance list \
      --compartment-id "$compartment_ocid" \
      --lifecycle-state PROVISIONING \
      --query 'length(data[?"freeform-tags".project=='"'"'acx'"'"'])' \
      --raw-output 2>/dev/null || echo "0"
  )"

  if [[ "$running_count" =~ ^[1-9] || "$provisioning_count" =~ ^[1-9] ]]; then
    return 0
  fi

  return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
TIMEOUT_BIN="$(detect_timeout_bin)"
if [[ -z "$TIMEOUT_BIN" ]]; then
  warn "Neither 'timeout' nor 'gtimeout' is available. Install coreutils (macOS: 'brew install coreutils') to enable per-attempt apply timeouts."
fi

preflight_check

attempt=0
retry_streak=0
while true; do
  for ad in "${ADS[@]}"; do
    attempt=$((attempt + 1))
    log "Attempt ${attempt}: availability_domain=${ad}"

    tmp_log="$(mktemp "${TMPDIR:-/tmp}/acx-oci-apply.XXXXXXXX")"
    _CURRENT_TMP_LOG="$tmp_log"
    apply_exit=0

    if [[ -n "$TIMEOUT_BIN" ]]; then
      "$TIMEOUT_BIN" "$APPLY_TIMEOUT_SEC" terraform apply \
        -auto-approve \
        -lock-timeout=30s \
        -var-file="$TFVARS_FILE" \
        -var "availability_domain=$ad" >"$tmp_log" 2>&1 || apply_exit=$?
    else
      terraform apply \
        -auto-approve \
        -lock-timeout=30s \
        -var-file="$TFVARS_FILE" \
        -var "availability_domain=$ad" >"$tmp_log" 2>&1 || apply_exit=$?
    fi

    if [[ "$apply_exit" -eq 0 ]]; then
      cat "$tmp_log" >> "$LOG_FILE"
      rm -f "$tmp_log"
      log "SUCCESS: Terraform apply completed in ${ad}"
      notify "ACX OCI apply succeeded in ${ad}"
      exit 0
    fi

    cat "$tmp_log" >> "$LOG_FILE"
    retry_reason="$(retry_reason_for "$apply_exit" "$tmp_log")"

    # Special case: LimitExceeded is only a graceful stop when we can verify
    # the target instance already exists.
    if [[ "$retry_reason" == "limit_exceeded" ]]; then
      rm -f "$tmp_log"
      if limit_exceeded_is_safe_success; then
        log "LIMIT_EXCEEDED: Verified existing ACX instance/state; treating as success."
        notify "ACX OCI apply stopped: LimitExceeded (existing instance verified)"
        exit 0
      fi
      log "FATAL: LIMIT_EXCEEDED without verified existing ACX instance. Likely quota exhaustion; provisioning not completed."
      notify "ACX OCI apply failed: LimitExceeded (no existing instance verified)"
      exit 1
    fi

    if [[ -z "$retry_reason" ]]; then
      rm -f "$tmp_log"
      log "FATAL: Non-retryable terraform apply error (exit=${apply_exit}). Aborting retry loop."
      notify "ACX OCI apply failed (non-retryable error)"
      exit 1
    fi

    retry_streak=$((retry_streak + 1))

    if [[ "$MAX_ATTEMPTS" -gt 0 && "$attempt" -ge "$MAX_ATTEMPTS" ]]; then
      rm -f "$tmp_log"
      log "Reached MAX_ATTEMPTS=${MAX_ATTEMPTS}. Aborting."
      notify "ACX OCI apply exhausted attempts"
      exit 1
    fi

    sleep_seconds="$(compute_sleep_seconds "$retry_reason" "$retry_streak" "$tmp_log")"
    rm -f "$tmp_log"
    log "Retryable error (${retry_reason}, exit=${apply_exit}) in ${ad}. Retrying in ${sleep_seconds}s."
    sleep "$sleep_seconds"
  done
done
