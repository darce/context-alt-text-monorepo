#!/usr/bin/env bash
# Remote-agent ping hygiene helpers. Sourceable for tests.
#
# Hung `codex exec ... ping` probes (ppid=1) leak pids and must be bounded and
# reaped. GNU timeout treats a duration of 0 as "no timeout", so PING_TIMEOUT_SEC
# must be a positive integer.
set -euo pipefail

PING_TIMEOUT_MIN=1
PING_TIMEOUT_MAX=120
ORPHAN_PING_STALE_MIN=1
ORPHAN_PING_STALE_MAX=3600
: "${PING_TIMEOUT_SEC:=5}"
: "${ORPHAN_PING_STALE_SEC:=30}"
: "${ORPHAN_PING_MATCH:=codex}"

acx_validate_positive_int() {
  local name="$1" value="$2" min="$3" max="$4"
  case "$value" in
    ''|*[!0-9]*)
      echo "remote_agent: ${name} must be an integer >= ${min} and <= ${max}" >&2
      return 2
      ;;
    0)
      echo "remote_agent: ${name} must be >= ${min} (0 disables the bound)" >&2
      return 2
      ;;
  esac
  if [ "$value" -lt "$min" ] || [ "$value" -gt "$max" ]; then
    echo "remote_agent: ${name} must be an integer >= ${min} and <= ${max} (got ${value})" >&2
    return 2
  fi
  return 0
}

acx_validate_ping_timeout() {
  local value="${1:-${PING_TIMEOUT_SEC}}"
  acx_validate_positive_int "PING_TIMEOUT_SEC" "$value" "$PING_TIMEOUT_MIN" "$PING_TIMEOUT_MAX" || return $?
  PING_TIMEOUT_SEC="$value"
}

acx_validate_orphan_ping_stale() {
  local value="${1:-${ORPHAN_PING_STALE_SEC}}"
  acx_validate_positive_int "ORPHAN_PING_STALE_SEC" "$value" "$ORPHAN_PING_STALE_MIN" "$ORPHAN_PING_STALE_MAX" || return $?
  ORPHAN_PING_STALE_SEC="$value"
}

acx_etime_to_seconds() {
  local etime="${1// /}" days=0 hours=0 minutes=0 seconds=0
  local rest="$etime" first second third
  if [[ "$rest" == *-* ]]; then
    days="${rest%%-*}"
    rest="${rest#*-}"
  fi
  case "$days" in ''|*[!0-9]*) return 1 ;; esac
  IFS=':' read -r first second third <<<"$rest" || true
  if [ -n "${third:-}" ]; then
    hours="$first"
    minutes="$second"
    seconds="$third"
  else
    minutes="$first"
    seconds="${second:-0}"
  fi
  case "$hours" in ''|*[!0-9]*) return 1 ;; esac
  case "$minutes" in ''|*[!0-9]*) return 1 ;; esac
  case "$seconds" in ''|*[!0-9]*) return 1 ;; esac
  echo $((days * 86400 + hours * 3600 + minutes * 60 + seconds))
}

acx_kill_pid() {
  local kill_bin pid="$1"
  kill_bin="$(type -P kill)" || {
    echo "remote_agent: kill is unavailable on PATH" >&2
    return 1
  }
  "$kill_bin" -TERM "$pid" 2>/dev/null
}

acx_run_bounded_ping() {
  acx_validate_ping_timeout || return $?
  if ! command -v timeout >/dev/null 2>&1; then
    echo "remote_agent: timeout is required to bound live pings" >&2
    return 2
  fi
  timeout -k 5 "$PING_TIMEOUT_SEC" "$@"
}

acx_reap_orphan_pings() {
  acx_validate_orphan_ping_stale || return $?
  local pid ppid etime cmd elapsed killed=0
  local ps_out
  ps_out="$(ps -eo pid=,ppid=,etime=,args=)" || {
    echo "remote_agent: ps failed; refusing to reap ping probes" >&2
    return 1
  }
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    read -r pid ppid etime cmd <<<"$line" || continue
    case "$pid" in ''|*[!0-9]*) continue ;; esac
    case "$ppid" in ''|*[!0-9]*) continue ;; esac
    [ "$ppid" = "1" ] || continue
    [ "$pid" != "$$" ] || continue
    [[ "$cmd" == *"$ORPHAN_PING_MATCH"* ]] || continue
    [[ "$cmd" == *ping* ]] || continue
    elapsed="$(acx_etime_to_seconds "$etime")" || continue
    if [ "$elapsed" -lt "$ORPHAN_PING_STALE_SEC" ]; then
      continue
    fi
    if acx_kill_pid "$pid"; then
      killed=$((killed + 1))
    fi
  done <<<"$ps_out"
  echo "remote_agent: reaped ${killed} stale orphan ping probe(s)"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

acx_validate_ping_timeout
acx_validate_orphan_ping_stale

cmd="${1:-}"
if [ "$#" -gt 0 ]; then
  shift
fi
case "$cmd" in
  reap-orphan-pings)
    acx_reap_orphan_pings
    ;;
  ping)
    acx_run_bounded_ping "$@"
    ;;
  ""|-h|--help|help)
    sed -n '2,7p' "$0"
    echo "Usage: $0 ping [--] <command>..." >&2
    echo "       $0 reap-orphan-pings" >&2
    exit 0
    ;;
  *)
    echo "remote_agent: unknown command: ${cmd}" >&2
    echo "Usage: $0 ping [--] <command>..." >&2
    echo "       $0 reap-orphan-pings" >&2
    exit 2
    ;;
esac
