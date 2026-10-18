#!/usr/bin/env bash
# Shared Caddy edge helper for the app portal and recognition deploys.
#
# Source this file; it defines functions and constants only. It never sets shell
# options, never installs traps, and never runs anything at load time, so the
# caller's `set -euo pipefail` and EXIT/ERR/HUP/INT/TERM traps keep their meaning.
#
# Frozen interface (lane impl-portal-shared-helper):
#   edge_lock_acquire <lock> <wait_s> [hold_max_s] [owner_pid|0]  -> prints handle; rc 0 held,
#                                                                 rc 75 busy (zero mutations), else rc 1/2
#   edge_lock_check <handle> [budget_s]                            -> rc 0 when the hold is alive and has
#                                                                 >= budget_s+1 s left; rc 3 expired, lost
#                                                                 or too short; rc 2 invalid input
#   edge_lock_release <handle> [deadline_s]                        -> rc 0 released, rc 3 expired or
#                                                                 owner-gone, rc 124 holder SIGKILLed,
#                                                                 rc 1 holder vanished while held (unknown)
#   edge_bounded_run <cmd> [args...]                               -> one protected operation under
#                                                                 EDGE_OP_DEADLINE; rc 124/137 on expiry
#   edge_effective_caddyfile <base> <live>                         -> stdout: base + verified managed block
#   edge_compose_args <base> <installed_overlay>                   -> sets EDGE_COMPOSE_ARGV=(-f ...)
#   edge_required_networks <base> <installed_overlay>              -> stdout: resolved caddy networks
#
# The lock is the existing activation.journal.lock inode. It is opened for append
# (never truncated, unlinked, or replaced). A short holder process keeps the flock
# across separate SSH operations; it exits on explicit release, on hold-cap expiry,
# or when the owner process (if given) disappears. Numeric arguments are canonical
# decimal (no leading zeros) of at most 18 digits, validated before any holder starts.

# Hosts the portal must never claim. Owned by the API and AuraFace stacks.
EDGE_PROTECTED_HOSTS="api.altcontext.com staging.api.altcontext.com dev.api.altcontext.com fir.dev.api.altcontext.com demo.altcontext.com 129-213-40-111.sslip.io dl.darce.xyz auraface.dev.altcontext.com auraface.staging.api.altcontext.com auraface.api.altcontext.com"
EDGE_LOCK_DEFAULT_HOLD=900
EDGE_LOCK_MAX_WAIT=3600
EDGE_LOCK_MAX_HOLD=7200
EDGE_LOCK_DEFAULT_DEADLINE=120
# Each protected operation (Docker, Caddy, health, compose reads) runs under this
# deadline. The lock must cover it plus the kill grace before the operation starts.
EDGE_OP_DEADLINE="${EDGE_OP_DEADLINE:-120}"
EDGE_OP_MAX_DEADLINE=600
EDGE_OP_KILL_GRACE=5
EDGE_COMPOSE_ARGV=()

_edge_err() {
  printf 'ERROR: %s\n' "$*" >&2
}

# Canonical decimal: "0", or no leading zero, digits only, at most 18 digits so the
# shell's 64-bit arithmetic cannot overflow. "08", "00" and "9223372036854775808" are refused.
_edge_is_uint() {
  case "${1:-}" in
    0) return 0 ;;
    [1-9]*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *[!0-9]*) return 1 ;;
  esac
  [ "${#1}" -le 18 ]
}

# Operation deadline: canonical integer 1..EDGE_OP_MAX_DEADLINE seconds.
_edge_op_deadline_ok() {
  _edge_is_uint "${1:-}" && [ "$1" -ge 1 ] && [ "$1" -le "$EDGE_OP_MAX_DEADLINE" ]
}

# A regular file that is not a symlink.
_edge_plain_file() {
  [ -n "${1:-}" ] && [ -f "$1" ] && [ ! -L "$1" ]
}

# True when PID names a live, non-zombie process.
_edge_pid_alive() {
  local pid="${1:-}" state="" stat_line=""
  _edge_is_uint "$pid" || return 1
  [ "$pid" -gt 0 ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  if [ -r "/proc/${pid}/stat" ]; then
    IFS= read -r stat_line <"/proc/${pid}/stat" 2>/dev/null || return 1
    state="${stat_line##*) }"
    state="${state%% *}"
  elif command -v ps >/dev/null 2>&1; then
    state="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  fi
  case "$state" in
    Z*) return 1 ;;
  esac
  return 0
}

_edge_lock_path_ok() {
  local lock="${1:-}" parent
  case "$lock" in
    /*) ;;
    *) return 1 ;;
  esac
  case "$lock" in
    *..* | *$'\n'*) return 1 ;;
  esac
  parent="${lock%/*}"
  [ -n "$parent" ] || parent=/
  [ -d "$parent" ] && [ ! -L "$parent" ] || return 1
  [ ! -L "$lock" ] || return 1
  [ ! -e "$lock" ] || [ -f "$lock" ] || return 1
  return 0
}

_edge_handle_ok() {
  local state="${1:-}"
  [ -n "$state" ] && [ -d "$state" ] && [ ! -L "$state" ] && [ -p "$state/hold" ]
}

# Publish a holder state atomically so the acquirer never reads a partial word.
_edge_publish() {
  printf '%s\n' "$2" >"$1/status.tmp" && command mv -f -- "$1/status.tmp" "$1/status"
}

# Holder body. Runs in a background subshell whose stdio the caller detaches. It takes
# the flock on the lock inode, then waits on a FIFO it holds open. The only child
# that ever sees the lock descriptor is the bounded `flock -w` that acquires it, and
# that child exits before the hold begins. Release sends SIGTERM; the holder exits
# and the kernel closes the descriptor, which drops the flock.
_edge_holder() {
  local lock="$1" wait_s="$2" hold_max="$3" owner="$4" state="$5" expires
  trap - ERR 2>/dev/null || true
  trap '' HUP INT
  # Only an explicit release publishes "released". A holder that dies without it
  # leaves "held" behind, which release reports as an unknown outcome.
  trap '_edge_publish "$state" released; exit 0' TERM
  printf '%s\n' "$BASHPID" >"$state/holder.pid"
  if ! exec 9>>"$lock"; then
    _edge_publish "$state" error
    exit 1
  fi
  if ! flock -w "$wait_s" 9; then
    _edge_publish "$state" busy
    exit 75
  fi
  if ! exec 8<>"$state/hold"; then
    _edge_publish "$state" error
    exit 1
  fi
  # Wall-clock expiry. Protected operations read it and refuse when it cannot cover them.
  expires=$(($(date +%s) + hold_max))
  printf '%s\n' "$expires" >"$state/expires" || {
    _edge_publish "$state" error
    exit 1
  }
  # If the acquirer already gave up and removed the state, nobody can release us:
  # exit now so the flock is dropped instead of held unobserved.
  _edge_publish "$state" held || exit 1
  while :; do
    read -r -t 1 -u 8 _ || :
    if [ "$owner" != 0 ] && ! _edge_pid_alive "$owner"; then
      _edge_publish "$state" owner-gone
      exit 0
    fi
    if [ "$(date +%s)" -ge "$expires" ]; then
      _edge_publish "$state" expired
      exit 0
    fi
  done
}

# edge_lock_acquire <lock> <wait_s> [hold_max_s] [owner_pid|0]
edge_lock_acquire() {
  local lock="${1:-}" wait_s="${2:-}" hold_max="${3:-}" owner="${4:-0}"
  local root state start limit status pid=""
  [ -n "$hold_max" ] || hold_max="$EDGE_LOCK_DEFAULT_HOLD"
  if ! _edge_is_uint "$wait_s" || [ "$wait_s" -gt "$EDGE_LOCK_MAX_WAIT" ]; then
    _edge_err "edge_lock_acquire: wait must be an integer 0..${EDGE_LOCK_MAX_WAIT} (got: ${wait_s})"
    return 2
  fi
  if ! _edge_is_uint "$hold_max" || [ "$hold_max" -lt 1 ] || [ "$hold_max" -gt "$EDGE_LOCK_MAX_HOLD" ]; then
    _edge_err "edge_lock_acquire: hold cap must be an integer 1..${EDGE_LOCK_MAX_HOLD} (got: ${hold_max})"
    return 2
  fi
  if ! _edge_is_uint "$owner"; then
    _edge_err "edge_lock_acquire: owner must be a PID or 0 (got: ${owner})"
    return 2
  fi
  if ! _edge_lock_path_ok "$lock"; then
    _edge_err "edge_lock_acquire: unsafe lock path: ${lock}"
    return 2
  fi
  if ! command -v flock >/dev/null 2>&1; then
    _edge_err "edge_lock_acquire: flock is required for deploy lock ${lock}"
    return 1
  fi
  root="${EDGE_LOCK_STATE_ROOT:-${TMPDIR:-/tmp}}"
  if [ ! -d "$root" ] || [ -L "$root" ]; then
    _edge_err "edge_lock_acquire: state root is missing or unsafe: ${root}"
    return 1
  fi
  state="$(mktemp -d "${root%/}/shared-edge-lock.XXXXXX")" || {
    _edge_err "edge_lock_acquire: cannot create handle state under ${root}"
    return 1
  }
  if ! mkfifo "$state/hold"; then
    command rm -rf -- "$state"
    _edge_err "edge_lock_acquire: cannot create holder FIFO"
    return 1
  fi
  (_edge_holder "$lock" "$wait_s" "$hold_max" "$owner" "$state") </dev/null >/dev/null 2>&1 &
  limit=$((wait_s + 10))
  start=$SECONDS
  status=""
  while :; do
    if [ -f "$state/status" ]; then
      IFS= read -r status <"$state/status" 2>/dev/null || status=""
      break
    fi
    if [ $((SECONDS - start)) -ge "$limit" ]; then
      status="timeout"
      break
    fi
    sleep 0.1 2>/dev/null || :
  done
  case "$status" in
    held)
      printf '%s\n' "$state"
      return 0
      ;;
    busy)
      command rm -rf -- "$state"
      return 75
      ;;
    *)
      if [ -f "$state/holder.pid" ]; then
        IFS= read -r pid <"$state/holder.pid" 2>/dev/null || pid=""
      fi
      if _edge_pid_alive "$pid"; then
        kill -KILL "$pid" 2>/dev/null || true
      fi
      command rm -rf -- "$state"
      _edge_err "edge_lock_acquire: holder did not confirm the lock (${status:-no status})"
      return 1
      ;;
  esac
}

# edge_lock_release <handle> [deadline_s]
edge_lock_release() {
  local state="${1:-}" deadline="${2:-}" pid="" status="" start rc=0
  [ -n "$deadline" ] || deadline="$EDGE_LOCK_DEFAULT_DEADLINE"
  if ! _edge_is_uint "$deadline" || [ "$deadline" -lt 1 ] || [ "$deadline" -gt 3600 ]; then
    _edge_err "edge_lock_release: deadline must be an integer 1..3600 (got: ${deadline})"
    return 2
  fi
  if ! _edge_handle_ok "$state"; then
    _edge_err "edge_lock_release: unknown or unsafe handle: ${state}"
    return 2
  fi
  if [ -f "$state/holder.pid" ]; then
    IFS= read -r pid <"$state/holder.pid" 2>/dev/null || pid=""
  fi
  if _edge_pid_alive "$pid"; then
    kill -TERM "$pid" 2>/dev/null || true
    start=$SECONDS
    while _edge_pid_alive "$pid"; do
      if [ $((SECONDS - start)) -ge "$deadline" ]; then
        kill -KILL "$pid" 2>/dev/null || true
        rc=124
        break
      fi
      sleep 0.1 2>/dev/null || :
    done
  fi
  IFS= read -r status <"$state/status" 2>/dev/null || status=""
  command rm -rf -- "$state"
  if [ "$rc" -ne 0 ]; then
    _edge_err "edge_lock_release: holder ${pid} did not exit within ${deadline}s; SIGKILL sent; release UNKNOWN"
    return "$rc"
  fi
  case "$status" in
    released)
      return 0
      ;;
    expired | owner-gone)
      _edge_err "edge_lock_release: shared edge lock ended ${status} before release; the protected operation was not fully serialized"
      return 3
      ;;
    held)
      _edge_err "edge_lock_release: holder exited while the lock was held without release; outcome UNKNOWN"
      return 1
      ;;
    *)
      _edge_err "edge_lock_release: holder state was ${status:-missing}"
      return 1
      ;;
  esac
}

# edge_lock_check <handle> [budget_s]
# Called before every protected operation. Passes only when the holder is alive, still
# reports "held", and its wall-clock expiry leaves at least budget_s+1 seconds. The default
# budget is the operation deadline plus the kill grace, so a bounded operation cannot
# outlive the hold that serialized it.
edge_lock_check() {
  local state="${1:-}" budget="${2:-}" status="" pid="" expires="" now left
  if ! _edge_op_deadline_ok "$EDGE_OP_DEADLINE"; then
    _edge_err "edge_lock_check: EDGE_OP_DEADLINE must be an integer 1..${EDGE_OP_MAX_DEADLINE} (got: ${EDGE_OP_DEADLINE})"
    return 2
  fi
  [ -n "$budget" ] || budget=$((EDGE_OP_DEADLINE + EDGE_OP_KILL_GRACE))
  if ! _edge_is_uint "$budget"; then
    _edge_err "edge_lock_check: budget must be a canonical integer (got: ${budget})"
    return 2
  fi
  if ! _edge_handle_ok "$state"; then
    _edge_err "edge_lock_check: unknown or unsafe handle: ${state}"
    return 2
  fi
  IFS= read -r status <"$state/status" 2>/dev/null || status=""
  if [ "$status" != held ]; then
    _edge_err "shared edge lock is ${status:-not held}; refusing the protected operation"
    return 3
  fi
  IFS= read -r pid <"$state/holder.pid" 2>/dev/null || pid=""
  if ! _edge_pid_alive "$pid"; then
    _edge_err "shared edge lock holder is gone; refusing the protected operation"
    return 3
  fi
  IFS= read -r expires <"$state/expires" 2>/dev/null || expires=""
  if ! _edge_is_uint "$expires"; then
    _edge_err "shared edge lock expiry is unreadable; refusing the protected operation"
    return 3
  fi
  now="$(date +%s)"
  EDGE_LOCK_CHECK_NOW="$now"
  left=$((expires - now))
  if [ "$left" -lt $((budget + 1)) ]; then
    _edge_err "shared edge lock has ${left}s left, too little for a ${budget}s protected operation; refusing"
    return 3
  fi
  return 0
}

# edge_bounded_run <command> [args...]
# One protected operation under EDGE_OP_DEADLINE. timeout terminates the whole process
# group on expiry (124, or 137 after the kill grace). Callers keep their own fd hygiene.
edge_bounded_run() {
  if ! _edge_op_deadline_ok "$EDGE_OP_DEADLINE"; then
    _edge_err "edge_bounded_run: EDGE_OP_DEADLINE must be an integer 1..${EDGE_OP_MAX_DEADLINE} (got: ${EDGE_OP_DEADLINE})"
    return 2
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    _edge_err "edge_bounded_run: timeout (coreutils) is required to bound protected operations"
    return 1
  fi
  timeout -k "$EDGE_OP_KILL_GRACE" "$EDGE_OP_DEADLINE" "$@"
}

# Prints "none" when live has no managed block, or "<begin_line> <end_line>" when it
# has exactly one well-formed block. Malformed or conflicting markers are refused.
_edge_portal_bounds() {
  python3 - "$1" "$EDGE_PROTECTED_HOSTS" <<'PY_CADDY'
import re
import sys
from pathlib import Path


def refuse(message):
    print("ERROR: live portal block " + message, file=sys.stderr)
    raise SystemExit(2)


def tokens(text):
    # Caddy v2 lexer: Unicode White_Space, token-initial comments, double/backtick
    # strings. Unsupported expansion/escape/heredoc/import syntax fails closed.
    whitespace = " \t\n\v\f\r\x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in whitespace:
            i += 1
            continue
        if ch == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end + 1
            continue
        quoted = ch in ('"', "`")
        value = ""
        if quoted:
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\" and quote == '"':
                    if i + 1 == len(text):
                        refuse("has an unterminated string")
                    following = text[i + 1]
                    value += following if following == '"' else "\\" + following
                    i += 2
                else:
                    value += text[i]
                    i += 1
            if i == len(text):
                refuse("has an unterminated string")
            i += 1
        else:
            while i < len(text) and text[i] not in whitespace:
                value += text[i]
                i += 1
            if "\\" in value or value.startswith("<<"):
                refuse("has unsupported escape or heredoc syntax")
        if "{$" in value or (not quoted and value == "import"):
            refuse("has unsupported expansion or import syntax")
        yield value, quoted


def hostname(address):
    address = address.lower()
    if address.startswith(("http://", "https://")):
        address = address.split("://", 1)[1]
    elif "://" in address:
        refuse("has an unsupported site address " + address)
    address = address.split("/", 1)[0]
    address = re.sub(r":[0-9]+$", "", address).removesuffix(".")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*", address):
        refuse("has an unsupported site address " + address)
    return address


try:
    # Only LF delimits the records extracted later by awk. Unicode whitespace
    # inside a record still delimits tokens, including same-line close/reopen.
    text = Path(sys.argv[1]).read_bytes().decode("utf-8")
    lines = text.split("\n")
    marked = [i for i, line in enumerate(lines) if "APP_PORTAL_VHOST" in line]
    if not marked:
        print("none")
        raise SystemExit(0)
    begins = [i for i in marked if lines[i].strip() == "# BEGIN APP_PORTAL_VHOST"]
    ends = [i for i in marked if lines[i].strip() == "# END APP_PORTAL_VHOST"]
    if len(marked) != 2 or len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        refuse("must have exactly one ordered BEGIN and END marker")
    begin, end = begins[0], ends[0]
    depth = sites = 0
    addresses = []
    protected = set(sys.argv[2].split())
    # Every body record is LF-terminated, including the one before END. Keep
    # that delimiter while validating so a final CRLF cannot become a bare CR.
    # Extraction below still emits the original bytes, including EOF at END.
    body = "".join(line + "\n" for line in lines[begin + 1:end])
    # Caddy ignores CR rather than treating it as a token boundary. CRLF is
    # supported; a standalone CR is refused rather than mis-parsed as a space.
    if "\r" in body.replace("\r\n", ""):
        refuse("has an unsupported standalone carriage return")
    for value, quoted in tokens(body.replace("\r\n", "\n")):
        if value == "{" and not quoted:
            if depth == 0:
                if not addresses:
                    refuse("has a site without an address")
                for address in addresses:
                    host = hostname(address)
                    if host in protected:
                        refuse("claims protected host " + host)
                addresses = []
                sites += 1
            depth += 1
        elif value == "}" and not quoted:
            depth -= 1
            if depth < 0 or addresses:
                refuse("has unbalanced braces")
        elif depth == 0:
            addresses.extend(part for part in value.split(",") if part)
        elif not quoted and ("{" in value or "}" in value):
            if not re.fullmatch(r"[^{}]*\{[a-zA-Z_][a-zA-Z0-9_.-]*\}[^{}]*", value):
                refuse("has unsupported brace syntax")
    if depth or addresses or not sites:
        refuse("has unbalanced braces or no complete site")
    print(begin + 1, end + 1)
except (OSError, UnicodeError) as exc:
    refuse("cannot be read: " + str(exc))
PY_CADDY
}

# edge_effective_caddyfile <base> <live>
edge_effective_caddyfile() {
  local base="${1:-}" live="${2:-}" tmp bounds bline eline out nl eol total
  if ! _edge_plain_file "$base"; then
    _edge_err "repository base Caddyfile must be a regular file: ${base}"
    return 2
  fi
  if ! _edge_plain_file "$live"; then
    _edge_err "live Caddyfile must be a regular file: ${live}"
    return 2
  fi
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/shared-edge-caddy.XXXXXX")" || return 1
  if ! command cp -- "$base" "$tmp/base" || ! command cp -- "$live" "$tmp/live"; then
    command rm -rf -- "$tmp"
    return 1
  fi
  if grep -q 'APP_PORTAL_VHOST' -- "$tmp/base"; then
    command rm -rf -- "$tmp"
    _edge_err "repository base Caddyfile must not carry managed portal markers"
    return 2
  fi
  if ! bounds="$(_edge_portal_bounds "$tmp/live")"; then
    command rm -rf -- "$tmp"
    return 2
  fi
  # Every producer's status is checked explicitly. The candidate is assembled in a file so
  # that a failed step can never be reported as an accepted candidate, even when the caller
  # tests this function inside `if` where errexit does not apply.
  out="$tmp/out"
  if [ "$bounds" = "none" ]; then
    if ! cat -- "$tmp/base" >"$out"; then
      _edge_effective_fail "$tmp" "cannot emit the repository base Caddyfile"
      return 1
    fi
  else
    bline="${bounds% *}"
    eline="${bounds#* }"
    if ! cat -- "$tmp/base" >"$out"; then
      _edge_effective_fail "$tmp" "cannot emit the repository base Caddyfile"
      return 1
    fi
    if [ -s "$tmp/base" ]; then
      nl="$(tail -c 1 "$tmp/base" | wc -l | tr -d ' ')" || nl=""
      case "$nl" in
        1) ;;
        0) printf '\n' >>"$out" || {
          _edge_effective_fail "$tmp" "cannot separate the managed block"
          return 1
        } ;;
        *)
          _edge_effective_fail "$tmp" "cannot inspect the repository base Caddyfile tail"
          return 1
          ;;
      esac
    fi
    printf '\n' >>"$out" || {
      _edge_effective_fail "$tmp" "cannot separate the managed block"
      return 1
    }
    # Preserve the managed block's bytes exactly, including an END marker that has no
    # final newline. awk print would always add one, so the last record is written bare
    # when the live file itself ends without a newline.
    eol="$(tail -c 1 "$tmp/live" | wc -l | tr -d ' ')" || eol=""
    total="$(wc -l <"$tmp/live" | tr -d ' ')" || total=""
    case "$eol" in
      0 | 1) ;;
      *)
        _edge_effective_fail "$tmp" "cannot inspect the live Caddyfile tail"
        return 1
        ;;
    esac
    case "$total" in
      '' | *[!0-9]*)
        _edge_effective_fail "$tmp" "cannot count the live Caddyfile records"
        return 1
        ;;
    esac
    [ "$eol" = 1 ] || total=$((total + 1))
    if ! LC_ALL=C awk -v a="$bline" -v b="$eline" -v records="$total" -v eol="$eol" '
      NR >= a && NR <= b {
        if (NR < records || eol == 1) print
        else printf "%s", $0
      }' "$tmp/live" >>"$out"; then
      _edge_effective_fail "$tmp" "cannot emit the managed portal block"
      return 1
    fi
  fi
  if ! cat -- "$out"; then
    _edge_effective_fail "$tmp" "cannot emit the candidate Caddyfile"
    return 1
  fi
  command rm -rf -- "$tmp"
  return 0
}

# Removes the scratch directory and reports why a candidate was not produced.
_edge_effective_fail() {
  command rm -rf -- "$1"
  _edge_err "edge_effective_caddyfile: $2"
}

# edge_compose_args <base> <installed_overlay>
edge_compose_args() {
  local base="${1:-}" overlay="${2:-}" signature
  local -a sources=("$base")
  EDGE_COMPOSE_ARGV=()
  if ! _edge_plain_file "$base"; then
    _edge_err "compose base must be a regular file: ${base}"
    return 2
  fi
  if [ -n "$overlay" ] && { [ -e "$overlay" ] || [ -L "$overlay" ]; }; then
    if ! _edge_plain_file "$overlay"; then
      _edge_err "installed overlay must be a regular non-symlink file: ${overlay}"
      return 2
    fi
    if grep -q '__APP_WWW__' -- "$overlay"; then
      _edge_err "installed overlay is an unresolved template (__APP_WWW__ present): ${overlay}"
      return 2
    fi
    sources+=("$overlay")
    EDGE_COMPOSE_ARGV=(-f "$base" -f "$overlay")
  else
    EDGE_COMPOSE_ARGV=(-f "$base")
  fi
  # Only this base opts into optional Aura networks. Resolve the actual Compose
  # producer, then select a complete, private generation. Raw YAML is never used
  # to infer membership or names. The installed portal overlay participates in
  # that same generation, so config/up/exec and required_networks agree.
  if grep -q '^# shared-edge: optional-auraface-networks$' -- "$base"; then
    signature="$(edge_bounded_run sha256sum -- "${sources[@]}")" || return 1
    if [ "${_EDGE_COMPOSE_SIGNATURE:-}" = "$signature" ] &&
      _edge_plain_file "${_EDGE_COMPOSE_TEMP:-}"; then
      EDGE_COMPOSE_ARGV=(-f "$_EDGE_COMPOSE_TEMP")
      return 0
    fi
    edge_compose_cleanup || return 1
    _edge_compose_generation || {
      EDGE_COMPOSE_ARGV=()
      return 1
    }
    _EDGE_COMPOSE_SIGNATURE="$signature"
  else
    edge_compose_cleanup || return 1
  fi
  return 0
}

# Explicit cleanup: callers source this library without acquiring traps/options.
# A command-substitution child must never remove its parent's selected generation.
edge_compose_cleanup() {
  if [ -n "${_EDGE_COMPOSE_TEMP:-}" ] && [ "${_EDGE_COMPOSE_TEMP_OWNER:-}" = "$BASHPID" ]; then
    edge_bounded_run rm -f -- "$_EDGE_COMPOSE_TEMP" || return 1
  fi
  _EDGE_COMPOSE_TEMP=""
  _EDGE_COMPOSE_TEMP_OWNER=""
  _EDGE_COMPOSE_SIGNATURE=""
}

_edge_compose_generation() {
  local model inventory tmp
  if ! command -v docker >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
    _edge_err "docker compose and jq are required to select the effective edge generation"
    return 1
  fi
  if ! model="$(edge_bounded_run docker compose "${EDGE_COMPOSE_ARGV[@]}" config --format json 9>&-)"; then
    _edge_err "cannot resolve the effective edge Compose model"
    return 1
  fi
  if ! inventory="$(edge_bounded_run docker network ls --format '{{.Name}}' 9>&-)"; then
    _edge_err "cannot read network inventory; refusing to infer optional Aura membership"
    return 1
  fi
  tmp="$(mktemp "${TMPDIR:-/tmp}/shared-edge-compose.XXXXXX.json")" || return 1
  # Compose config emits fully resolved names and absolute bind paths. Preserve
  # them in a full JSON generation rather than relying on list-merge semantics.
  # Drop ONLY absent staging/prod Aura memberships and their unused declarations;
  # keep generic, FIR and dev Aura networks and every installed-overlay volume.
  if ! printf '%s' "$model" | jq --arg inventory "$inventory" '
    if (.services.caddy.networks | type) != "object" or (.networks | type) != "object"
    then error("expected resolved Caddy network maps") else . end
    | ($inventory | split("\n")) as $present
    | . as $model
    | [.services.caddy.networks | keys[]
       | . as $key | ($model.networks[$key].name // $key) as $name
       | select(($name == "acx-staging-auraface-net" or $name == "acx-prod-auraface-net")
                and ($present | index($name) | not))] as $absent
    | del(.services.caddy.networks[$absent[]])
    | [.services[].networks // {} | keys[]] as $used
    | .networks |= with_entries(select(.key as $key | $used | index($key)))
    | if (.services.caddy.networks | length) == 0 then error("empty Caddy membership") else . end
    | walk(if type == "string" then gsub("\\$"; "$$") else . end)
  ' >"$tmp"; then
    edge_bounded_run rm -f -- "$tmp"
    _edge_err "cannot produce the effective edge Compose generation"
    return 1
  fi
  _EDGE_COMPOSE_TEMP="$tmp"
  _EDGE_COMPOSE_TEMP_OWNER="$BASHPID"
  EDGE_COMPOSE_ARGV=(-f "$tmp")
}

# edge_required_networks <base> <installed_overlay>
# Resolves services.caddy.networks through the selected Compose model. Names are the
# model's actual network names (`name:` when declared, else the key). Empty results
# are refused rather than inferred.
edge_required_networks() (
  local base="${1:-}" overlay="${2:-}" model names name
  edge_compose_args "$base" "$overlay" || return 2
  if ! command -v docker >/dev/null 2>&1; then
    _edge_err "docker is required to resolve caddy networks"
    return 1
  fi
  if ! command -v jq >/dev/null 2>&1; then
    _edge_err "jq is required to resolve caddy networks"
    return 1
  fi
  if ! model="$(edge_bounded_run docker compose "${EDGE_COMPOSE_ARGV[@]}" config --format json 9>&-)"; then
    edge_compose_cleanup || return 1
    _edge_err "docker compose config failed for ${base}"
    return 1
  fi
  edge_compose_cleanup || return 1
  if ! names="$(printf '%s' "$model" | jq -r '
      (.services.caddy.networks // {}) as $n
      | (if ($n | type) == "array" then $n[] else ($n | keys[]) end) as $k
      | (.networks[$k].name // $k)' 2>/dev/null)"; then
    _edge_err "cannot read caddy networks from the compose model"
    return 1
  fi
  if [ -z "$names" ]; then
    _edge_err "compose model declares no caddy networks; refusing to infer membership"
    return 1
  fi
  while IFS= read -r name; do
    case "$name" in
      '' | *[!A-Za-z0-9_.-]*)
        _edge_err "unsafe caddy network name in compose model: ${name}"
        return 1
        ;;
    esac
  done <<EOF
$names
EOF
  printf '%s\n' "$names" | LC_ALL=C sort -u
  return 0
)
