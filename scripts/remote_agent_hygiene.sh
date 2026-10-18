#!/usr/bin/env bash
# Remote-agent ping hygiene helpers (sourced by the plugin-managed scripts/remote_agent.sh transport overlay, which stays untracked). Sourceable for tests.
#
# Hung `codex exec ... ping` probes (ppid=1) leak pids and must be bounded and
# reaped. A ping with no deadline is an unbounded blocking call (RES-02). GNU
# timeout treats duration 0 as "no timeout", so PING_TIMEOUT_SEC must be a
# positive integer; missing/empty values fall back to a bounded default and log
# (SECD-05). Live pings use a portable watchdog so the bound does not depend on
# GNU timeout(1).
#
# OVERLAY_SEAM_CONTRACT
# The plugin-managed scripts/remote_agent.sh overlay MUST:
#   1. source this file (remote_agent_hygiene.sh)
#   2. route hung ping probes through acx_run_bounded_ping
#   3. call acx_reap_orphan_pings on the live transport
# Tests assert this contract against the overlay when present, and against
# this file's CLI / sourceable helpers when the overlay is absent.
set -euo pipefail

PING_TIMEOUT_MIN=1
PING_TIMEOUT_MAX=120
PING_TIMEOUT_DEFAULT=5
ORPHAN_PING_STALE_MIN=1
ORPHAN_PING_STALE_MAX=3600
ORPHAN_PING_STALE_DEFAULT=30
: "${ORPHAN_PING_MATCH:=codex}"

if [ -z "${PING_TIMEOUT_SEC:-}" ]; then
  echo "remote_agent: PING_TIMEOUT_SEC unset or empty; defaulting to ${PING_TIMEOUT_DEFAULT}" >&2
  PING_TIMEOUT_SEC="$PING_TIMEOUT_DEFAULT"
fi
: "${ORPHAN_PING_STALE_SEC:=$ORPHAN_PING_STALE_DEFAULT}"

acx_validate_positive_int() {
  local name="$1" value="$2" min="$3" max="$4" normalized
  case "$value" in
    ''|*[!0-9]*)
      echo "remote_agent: ${name} must be an integer >= ${min} and <= ${max}" >&2
      return 2
      ;;
  esac
  # Force decimal so zero-padded values (08, 00) are not parsed as octal.
  normalized=$((10#$value))
  if [ "$normalized" -eq 0 ]; then
    echo "remote_agent: ${name} must be >= ${min} (0 disables the bound)" >&2
    return 2
  fi
  if [ "$normalized" -lt "$min" ] || [ "$normalized" -gt "$max" ]; then
    echo "remote_agent: ${name} must be an integer >= ${min} and <= ${max} (got ${value})" >&2
    return 2
  fi
  return 0
}

acx_validate_ping_timeout() {
  local value="${1:-${PING_TIMEOUT_SEC}}"
  acx_validate_positive_int "PING_TIMEOUT_SEC" "$value" "$PING_TIMEOUT_MIN" "$PING_TIMEOUT_MAX" || return $?
  PING_TIMEOUT_SEC=$((10#$value))
}

acx_validate_orphan_ping_stale() {
  local value="${1:-${ORPHAN_PING_STALE_SEC}}"
  acx_validate_positive_int "ORPHAN_PING_STALE_SEC" "$value" "$ORPHAN_PING_STALE_MIN" "$ORPHAN_PING_STALE_MAX" || return $?
  ORPHAN_PING_STALE_SEC=$((10#$value))
}

acx_cmd_has_ping_token() {
  # Distinct argv token, not a substring of ping-hygiene / mapping / pinging.
  local ping_token='(^|[[:space:]])ping([[:space:]]|$)'
  [[ "$1" =~ $ping_token ]]
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
  # ps etime zero-pads fields; unprefixed 08 is invalid octal in $(( )).
  echo $((10#$days * 86400 + 10#$hours * 3600 + 10#$minutes * 60 + 10#$seconds))
}

acx_kill_pid() {
  local kill_bin pid="$1" i=0
  kill_bin="$(type -P kill)" || {
    echo "remote_agent: kill is unavailable on PATH" >&2
    return 1
  }
  "$kill_bin" -TERM "$pid" 2>/dev/null || return 1
  # Bounded wait (~2s) so a cooperative process can exit on TERM.
  while [ "$i" -lt 20 ]; do
    "$kill_bin" -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
    i=$((i + 1))
  done
  "$kill_bin" -KILL "$pid" 2>/dev/null || true
  # Brief reap window: a just-killed pid can still look alive as a zombie.
  i=0
  while [ "$i" -lt 5 ]; do
    "$kill_bin" -0 "$pid" 2>/dev/null || return 0
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}

acx_ping_children_of() {
  local parent="$1" out child cpid cppid
  if command -v pgrep >/dev/null 2>&1; then
    out="$(pgrep -P "$parent" 2>/dev/null || true)"
    while IFS= read -r child; do
      child="${child// /}"
      case "$child" in
        ''|*[!0-9]*) continue ;;
      esac
      printf '%s\n' "$child"
    done <<EOF
${out}
EOF
    return 0
  fi
  command -v ps >/dev/null 2>&1 || return 0
  out="$(ps -eo pid=,ppid= 2>/dev/null || true)"
  while IFS= read -r child; do
    [ -n "$child" ] || continue
    read -r cpid cppid _ <<<"$child" || continue
    cpid="${cpid// /}"
    cppid="${cppid// /}"
    case "$cpid" in ''|*[!0-9]*) continue ;; esac
    case "$cppid" in ''|*[!0-9]*) continue ;; esac
    [ "$cppid" = "$parent" ] || continue
    printf '%s\n' "$cpid"
  done <<EOF
${out}
EOF
}

acx_ping_list_descendants() {
  local parent="$1" child children
  children="$(acx_ping_children_of "$parent")"
  while IFS= read -r child; do
    child="${child// /}"
    case "$child" in
      ''|*[!0-9]*) continue ;;
    esac
    acx_ping_list_descendants "$child"
    printf '%s\n' "$child"
  done <<EOF
${children}
EOF
}

acx_kill_ping_tree() {
  local pid="$1" used_setsid="${2:-}" child descendants
  if [ -n "$used_setsid" ]; then
    # Negative PGID kills the whole session started by setsid.
    kill -TERM -- "-$pid" 2>/dev/null || true
    sleep 0.1
    kill -KILL -- "-$pid" 2>/dev/null || true
    return 0
  fi
  # Capture the tree before signaling. TERM on the parent can reparent a
  # stubborn descendant to init (HARNC-R-08), hiding it from a later scan.
  descendants="$(acx_ping_list_descendants "$pid")"
  while IFS= read -r child; do
    child="${child// /}"
    case "$child" in
      ''|*[!0-9]*) continue ;;
    esac
    kill -TERM "$child" 2>/dev/null || true
  done <<EOF
${descendants}
EOF
  kill -TERM "$pid" 2>/dev/null || true
  sleep 0.1
  while IFS= read -r child; do
    child="${child// /}"
    case "$child" in
      ''|*[!0-9]*) continue ;;
    esac
    kill -KILL "$child" 2>/dev/null || true
  done <<EOF
${descendants}
EOF
  kill -KILL "$pid" 2>/dev/null || true
}

acx_run_bounded_ping() {
  acx_validate_ping_timeout || return $?
  local ping_pid start now deadline used_setsid="" restore_monitor=0 ping_rc=0
  if [ "$#" -eq 0 ]; then
    echo "remote_agent: ping requires a command" >&2
    return 2
  fi
  if [ "$1" = "--" ]; then
    shift
  fi
  if [ "$#" -eq 0 ]; then
    echo "remote_agent: ping requires a command" >&2
    return 2
  fi
  start="$(date +%s)" || {
    echo "remote_agent: could not read the clock" >&2
    return 2
  }
  case "$start" in
    ''|*[!0-9]*)
      echo "remote_agent: clock returned a non-numeric value" >&2
      return 2
      ;;
  esac
  # util-linux setsid double-forks when the background job is already a
  # process-group leader (bash job control / set -m). $! then dies immediately
  # and the real command is reparented to init. Disable monitor mode first.
  case "$-" in
    *m*) restore_monitor=1; set +m ;;
  esac
  if command -v setsid >/dev/null 2>&1; then
    used_setsid="$(command -v setsid)"
    "$used_setsid" "$@" &
  else
    "$@" &
  fi
  ping_pid=$!
  deadline=$((start + PING_TIMEOUT_SEC))
  ping_rc=0
  while kill -0 "$ping_pid" 2>/dev/null; do
    now="$(date +%s)" || {
      acx_kill_ping_tree "$ping_pid" "$used_setsid"
      wait "$ping_pid" 2>/dev/null || true
      echo "remote_agent: could not read the clock while pinging" >&2
      ping_rc=2
      break
    }
    case "$now" in
      ''|*[!0-9]*)
        acx_kill_ping_tree "$ping_pid" "$used_setsid"
        wait "$ping_pid" 2>/dev/null || true
        echo "remote_agent: clock returned a non-numeric value" >&2
        ping_rc=2
        break
        ;;
    esac
    if [ "$now" -ge "$deadline" ]; then
      acx_kill_ping_tree "$ping_pid" "$used_setsid"
      wait "$ping_pid" 2>/dev/null || true
      ping_rc=124
      break
    fi
    sleep 0.1
  done
  if [ "$ping_rc" -eq 0 ]; then
    wait "$ping_pid" && ping_rc=0 || ping_rc=$?
  fi
  if [ "$restore_monitor" -eq 1 ]; then
    set -m
  fi
  return "$ping_rc"
}

acx_reap_orphan_pings() {
  acx_validate_orphan_ping_stale || return $?
  local pid ppid etime cmd elapsed killed=0 parse_failed=0
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
    acx_cmd_has_ping_token "$cmd" || continue
    if ! elapsed="$(acx_etime_to_seconds "$etime")"; then
      echo "remote_agent: skipping pid ${pid}: could not parse etime '${etime}'" >&2
      parse_failed=$((parse_failed + 1))
      continue
    fi
    if [ "$elapsed" -lt "$ORPHAN_PING_STALE_SEC" ]; then
      continue
    fi
    if acx_kill_pid "$pid"; then
      killed=$((killed + 1))
    fi
  done <<<"$ps_out"
  echo "remote_agent: reaped ${killed} stale orphan ping probe(s)"
  if [ "$parse_failed" -gt 0 ]; then
    echo "remote_agent: skipped ${parse_failed} ping probe(s) with unparseable etime" >&2
  fi
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

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
    sed -n '2,10p' "$0"
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
