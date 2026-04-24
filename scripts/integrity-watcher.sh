#!/usr/bin/env bash
# integrity-watcher.sh — out-of-band write attribution daemon.
#
# AHMCP-19 (item I from the AHMCP-18 tech-debt assessment): wraps fswatch
# (or inotifywait on Linux) over a configurable set of repo paths and
# records every modify/create/remove event with enough context to attribute
# the write to a specific PID and command line. Closes AHMCP-16-FU-02 by
# giving the next session a positive evidence trail when an out-of-band
# actor (stale editor buffer, parallel agent, IDE auto-save) clobbers a
# file in the working tree.
#
# Output: one JSON line per event written to .task-state/integrity-watcher.jsonl
# in the primary worktree's state dir. Lines are bounded — the script
# rotates the log when it exceeds INTEGRITY_WATCHER_MAX_BYTES (default 5 MB).
#
# Usage:
#   ./scripts/integrity-watcher.sh                 # watch the default paths
#   ./scripts/integrity-watcher.sh path1 path2 ... # watch explicit paths
#   ./scripts/integrity-watcher.sh --smoke         # emit one daemon_start event and exit (for tests)
#
# Environment:
#   INTEGRITY_WATCHER_MAX_BYTES   max log size before rotation (default 5242880)
#   INTEGRITY_WATCHER_LOG         override the output log path
#   INTEGRITY_WATCHER_BACKEND     force "fswatch" or "inotifywait" (auto by default)
#
# This script is observation-only. It never modifies the watched paths.
# A SIGINT (Ctrl+C) or SIGTERM exits cleanly and writes a daemon_stop event.

set -euo pipefail

SMOKE_MODE=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --smoke)
      SMOKE_MODE=1
      ;;
    *)
      ARGS+=("$arg")
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve the primary worktree root via git rev-parse --git-common-dir.
# AHMCP-16-style resolution: works from any linked worktree.
# ---------------------------------------------------------------------------

resolve_primary_root() {
  local start_dir="$1"
  local common_dir
  if ! common_dir="$(git -C "$start_dir" rev-parse --git-common-dir 2>/dev/null)"; then
    return 1
  fi
  if [[ "$common_dir" != /* ]]; then
    common_dir="$(cd "$start_dir" && cd "$common_dir" && pwd)"
  fi
  if [[ "$(basename "$common_dir")" == ".git" ]]; then
    dirname "$common_dir"
  else
    echo "$common_dir"
  fi
}

START_DIR="${PWD}"
PRIMARY_ROOT="$(resolve_primary_root "$START_DIR" 2>/dev/null || true)"
if [[ -z "$PRIMARY_ROOT" ]]; then
  echo "❌ integrity-watcher: could not resolve primary git worktree from $START_DIR" >&2
  exit 1
fi

STATE_DIR="$PRIMARY_ROOT/.task-state"
mkdir -p "$STATE_DIR"
LOG_PATH="${INTEGRITY_WATCHER_LOG:-$STATE_DIR/integrity-watcher.jsonl}"
MAX_BYTES="${INTEGRITY_WATCHER_MAX_BYTES:-5242880}"
SESSION_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"

# ---------------------------------------------------------------------------
# Default watched paths: root-owned lifecycle and contract surfaces. The MCP
# package implementations now live in external repositories. Override by
# passing explicit args.
# ---------------------------------------------------------------------------

if [[ "${#ARGS[@]}" -eq 0 ]]; then
  WATCH_PATHS=(
    "$PRIMARY_ROOT/scripts"
    "$PRIMARY_ROOT/mk"
    "$PRIMARY_ROOT/docs/agentic/contracts"
  )
else
  WATCH_PATHS=("${ARGS[@]}")
fi

# Filter out paths that do not exist so the watcher does not abort on
# partial checkouts.
EXISTING_PATHS=()
for path in "${WATCH_PATHS[@]}"; do
  if [[ -e "$path" ]]; then
    EXISTING_PATHS+=("$path")
  fi
done
if [[ "${#EXISTING_PATHS[@]}" -eq 0 && "$SMOKE_MODE" -eq 0 ]]; then
  echo "❌ integrity-watcher: no existing paths to watch" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Backend selection. Prefer fswatch on macOS; fall back to inotifywait on
# Linux. Both surfaces emit one path per event line on stdout. In smoke
# mode the backend is irrelevant — we never call it.
# ---------------------------------------------------------------------------

BACKEND="${INTEGRITY_WATCHER_BACKEND:-}"
if [[ -z "$BACKEND" && "$SMOKE_MODE" -eq 0 ]]; then
  if command -v fswatch >/dev/null 2>&1; then
    BACKEND="fswatch"
  elif command -v inotifywait >/dev/null 2>&1; then
    BACKEND="inotifywait"
  else
    cat >&2 <<'EOF'
❌ integrity-watcher: neither fswatch nor inotifywait is available.

  macOS:   brew install fswatch
  Linux:   apt install inotify-tools  (or distro equivalent)

  Force a backend with INTEGRITY_WATCHER_BACKEND=fswatch|inotifywait
  if you have a non-default install location.
EOF
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# Log rotation. The watcher runs for the duration of a development
# session, so the log can grow if the user is editing actively. We
# rotate to <log>.1 once it crosses INTEGRITY_WATCHER_MAX_BYTES; older
# rotations are dropped.
# ---------------------------------------------------------------------------

rotate_if_oversized() {
  if [[ ! -f "$LOG_PATH" ]]; then
    return 0
  fi
  local size
  if size=$(stat -f%z "$LOG_PATH" 2>/dev/null); then
    :
  elif size=$(stat -c%s "$LOG_PATH" 2>/dev/null); then
    :
  else
    return 0
  fi
  if (( size > MAX_BYTES )); then
    mv "$LOG_PATH" "$LOG_PATH.1"
    : > "$LOG_PATH"
  fi
}

# ---------------------------------------------------------------------------
# Event recording. Emits a single JSON object on stdout (then appended
# to the log file by the caller). The fields are:
#   ts          ISO-8601 UTC timestamp with microseconds when supported
#   event_kind  daemon_start | daemon_stop | write
#   path        absolute path of the affected file (write events only)
#   git_head    current HEAD SHA (write events only)
#   git_branch  current branch (write events only)
#   dirty       array of repo-relative paths reported by git diff --name-only HEAD
#   holders     array of {pid, command, name} entries from lsof for the affected path
#   session_id  identifier of this watcher invocation
#
# We deliberately invoke `python3` for the JSON encode rather than
# hand-rolling string escapes — bash quoting and JSON quoting collide
# the moment a path contains a quote, backslash, or newline.
# ---------------------------------------------------------------------------

emit_event() {
  local event_kind="$1"
  local affected_path="${2:-}"
  # Use Python for the timestamp because BSD `date` (macOS) does not
  # support %N for sub-second precision and silently emits the literal
  # `%6N`. Python's datetime.utcnow().isoformat() gives microsecond
  # precision portably across macOS and Linux.
  local ts
  ts="$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))')"

  local git_head=""
  local git_branch=""
  local dirty_lines=""
  if [[ "$event_kind" == "write" ]]; then
    git_head="$(git -C "$PRIMARY_ROOT" rev-parse HEAD 2>/dev/null || true)"
    git_branch="$(git -C "$PRIMARY_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    dirty_lines="$(git -C "$PRIMARY_ROOT" diff --name-only HEAD 2>/dev/null || true)"
  fi

  local holders_lines=""
  if [[ -n "$affected_path" && -e "$affected_path" ]]; then
    holders_lines="$(lsof -F pcn "$affected_path" 2>/dev/null || true)"
  fi

  python3 - "$event_kind" "$affected_path" "$ts" "$git_head" "$git_branch" "$SESSION_ID" "$dirty_lines" "$holders_lines" <<'PY'
import json
import sys

event_kind, path, ts, git_head, git_branch, session_id, dirty_blob, holders_blob = sys.argv[1:9]

dirty = [line for line in dirty_blob.splitlines() if line]

# lsof -F pcn outputs grouped records: each record starts with `p<pid>`
# followed by `c<command>` and `n<name>` lines. Group them into objects.
holders = []
current = None
for line in holders_blob.splitlines():
    if not line:
        continue
    field, value = line[0], line[1:]
    if field == "p":
        if current is not None:
            holders.append(current)
        current = {"pid": int(value) if value.isdigit() else value}
    elif field == "c" and current is not None:
        current["command"] = value
    elif field == "n" and current is not None:
        current["name"] = value
if current is not None:
    holders.append(current)

payload = {
    "ts": ts,
    "event_kind": event_kind,
    "session_id": session_id,
}
if path:
    payload["path"] = path
if event_kind == "write":
    payload["git_head"] = git_head or None
    payload["git_branch"] = git_branch or None
    payload["dirty"] = dirty
    payload["holders"] = holders

print(json.dumps(payload, sort_keys=True))
PY
}

write_event() {
  local event_kind="$1"
  local affected_path="${2:-}"
  rotate_if_oversized
  emit_event "$event_kind" "$affected_path" >> "$LOG_PATH"
}

# ---------------------------------------------------------------------------
# Daemon lifecycle. Trap signals to write a final daemon_stop event so
# the log shows clean session boundaries.
# ---------------------------------------------------------------------------

cleanup() {
  write_event "daemon_stop"
  exit 0
}
trap cleanup INT TERM

write_event "daemon_start"

if [[ "$SMOKE_MODE" -eq 1 ]]; then
  # Smoke mode: emit one daemon_start (already done above), one synthetic
  # write event so callers can validate the schema, and one daemon_stop.
  # Used by tests/test_lifecycle_scripts.py to verify the script's JSON
  # output without requiring fswatch/inotifywait.
  if [[ "${#EXISTING_PATHS[@]}" -gt 0 ]]; then
    write_event "write" "${EXISTING_PATHS[0]}"
  fi
  write_event "daemon_stop"
  exit 0
fi

echo "→ integrity-watcher: backend=$BACKEND log=$LOG_PATH session=$SESSION_ID" >&2
echo "→ integrity-watcher: watching ${#EXISTING_PATHS[@]} path(s):" >&2
for path in "${EXISTING_PATHS[@]}"; do
  echo "    - $path" >&2
done

# ---------------------------------------------------------------------------
# Watcher loop. fswatch and inotifywait both emit one absolute path per
# line on stdout when configured for line-buffered batch mode. We read
# from a process-substitution stream so the trap can fire on Ctrl+C
# without leaving an orphaned watcher.
# ---------------------------------------------------------------------------

start_watcher_stream() {
  if [[ "$BACKEND" == "fswatch" ]]; then
    fswatch \
      --recursive \
      --event Created \
      --event Updated \
      --event Removed \
      --event Renamed \
      --event MovedFrom \
      --event MovedTo \
      "${EXISTING_PATHS[@]}"
  else
    inotifywait \
      --monitor \
      --recursive \
      --format '%w%f' \
      --event modify,create,delete,move,close_write \
      "${EXISTING_PATHS[@]}"
  fi
}

exec 3< <(start_watcher_stream)
while IFS= read -r event_path <&3; do
  [[ -z "$event_path" ]] && continue
  write_event "write" "$event_path"
done

cleanup
