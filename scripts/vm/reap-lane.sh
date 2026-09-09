#!/usr/bin/env bash
# Guarded lane-clone reaper. Default is dry-run; --yes actually rm -rf.
# Usage:
#   reap-lane.sh [--yes] [--log FILE] PATH...
#   reap-lane.sh [--yes] [--log FILE] --all ROOT [--all ROOT ...]
set -euo pipefail

export GIT_TERMINAL_PROMPT=0

usage() {
  echo "Usage: reap-lane.sh [--yes] [--log FILE] [--archive-to REPO.git] PATH..." >&2
  echo "       reap-lane.sh [--yes] [--log FILE] --all ROOT [--all ROOT ...]" >&2
  echo "Exit status 3 means another reaper holds the whole-sweep lock." >&2
  echo "Exit status 4 means a pressured --yes sweep found candidates but reaped none." >&2
  exit 2
}

# Decode a file-URL path without depending on Python or a GNU-only utility.
# The decoded value is returned in decoded_file_path so trailing newlines in a
# legal pathname are not stripped by command substitution. NUL cannot exist in
# a pathname and cannot be represented in a shell variable, so reject it.
percent_decode_file_path() {
  local rest="$1" decoded="" prefix hex char
  while [[ "$rest" == *%* ]]; do
    prefix="${rest%%\%*}"
    decoded="${decoded}${prefix}"
    rest="${rest#*%}"
    [[ "${#rest}" -ge 2 ]] || return 1
    hex="${rest:0:2}"
    case "$hex" in
      ''|*[!0-9A-Fa-f]*) return 1 ;;
      00) return 1 ;;
    esac
    printf -v char '%b' "\\x${hex}" || return 1
    decoded="${decoded}${char}"
    rest="${rest:2}"
  done
  decoded_file_path="${decoded}${rest}"
}

: "${HOME:?HOME must be set}"

yes=0
log="${HOME}/reap-lane.log"
all_roots=()
archive_to=""
archive_to_real=""
paths=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) yes=1; shift ;;
    --archive-to)
      [[ $# -ge 2 ]] || usage
      archive_to="$2"
      shift 2
      ;;
    --log)
      [[ $# -ge 2 ]] || usage
      log="$2"
      shift 2
      ;;
    --all)
      # Repeatable: one cron line has to sweep every lane root, and a
      # last-one-wins flag would silently reap only the final one.
      [[ $# -ge 2 ]] || usage
      all_roots+=("$2")
      shift 2
      ;;
    -h|--help) usage ;;
    --) shift; paths+=("$@"); break ;;
    -*)
      echo "reap-lane: unknown option: $1" >&2
      exit 2
      ;;
    *) paths+=("$1"); shift ;;
  esac
done

if [[ ${#all_roots[@]} -eq 0 && ${#paths[@]} -eq 0 ]]; then
  usage
fi

# Canonicalize filesystem-backed archives once, before inspecting candidates.
# Remote transports cannot be compared to a lane's local realpath.
if [[ -n "$archive_to" ]]; then
  archive_path=""
  archive_is_local=0
  case "$archive_to" in
    file://*)
      file_url_path="${archive_to#file://}"
      case "$file_url_path" in
        /*) ;;
        [Ll][Oo][Cc][Aa][Ll][Hh][Oo][Ss][Tt]/*)
          file_url_path="/${file_url_path#*/}"
          ;;
        *)
          echo "reap-lane: unsupported file URL authority: $archive_to" >&2
          exit 2
          ;;
      esac
      if ! percent_decode_file_path "$file_url_path"; then
        echo "reap-lane: invalid percent encoding in archive URL: $archive_to" >&2
        exit 2
      fi
      archive_path="$decoded_file_path"
      archive_is_local=1
      ;;
    *://*|*:* ) ;;
    *) archive_path="$archive_to"; archive_is_local=1 ;;
  esac
  if [[ -n "$archive_path" ]]; then
    # A destination that does not exist yet must still reach the archive step
    # so the operator sees "could not archive" rather than a startup failure;
    # canonicalize through its parent (macOS realpath has no -m).
    if ! archive_to_real="$(realpath "$archive_path" 2>/dev/null)"; then
      archive_parent="$(cd "$(dirname "$archive_path")" 2>/dev/null && pwd -P)" || archive_parent=""
      if [[ -n "$archive_parent" ]]; then
        archive_to_real="${archive_parent%/}/$(basename "$archive_path")"
      else
        archive_to_real="$archive_path"
      fi
    fi
    # A canonical absolute destination also makes a relative local path behave
    # consistently when git is invoked with -C for different lane checkouts.
    if [[ "$archive_is_local" -eq 1 ]]; then
      archive_to="$archive_to_real"
    fi
  fi
fi

home_real="$(realpath "$HOME")" || {
  echo "reap-lane: could not resolve HOME: $HOME" >&2
  exit 1
}

sandbox_roots=("${home_real}/grok-sandbox")
remote_agent_root_real=""
invalid_remote_agent_root_real=""
if [[ -n "${WORKBAY_REMOTE_AGENT_ROOT:-}" ]]; then
  remote_agent_root_real="$(realpath "$WORKBAY_REMOTE_AGENT_ROOT" 2>/dev/null || true)"
  case "$remote_agent_root_real" in
    "${home_real}"/*)
      if [[ "$remote_agent_root_real" != "${home_real}/grok-sandbox" ]]; then
        sandbox_roots+=("$remote_agent_root_real")
      fi
      ;;
    '') ;;
    *) invalid_remote_agent_root_real="$remote_agent_root_real" ;;
  esac
fi

# Destructive sandbox sweeps must participate in the materializer's flock
# contract. Detect that unsupported mode once, before acquiring the sweep lock
# or inspecting any lane; dry-runs remain useful on hosts without flock.
if [[ "$yes" -eq 1 ]] && ! command -v flock >/dev/null 2>&1; then
  sandbox_scope=0
  for requested_root in ${all_roots[@]+"${all_roots[@]}"}; do
    requested_real="$(realpath "$requested_root" 2>/dev/null || true)"
    for sandbox_root in "${sandbox_roots[@]}"; do
      if [[ "$requested_real" == "$sandbox_root" ]]; then
        sandbox_scope=1
        break 2
      fi
    done
  done
  if [[ "$sandbox_scope" -eq 0 ]]; then
    for requested_path in ${paths[@]+"${paths[@]}"}; do
      requested_real="$(realpath "$requested_path" 2>/dev/null || true)"
      for sandbox_root in "${sandbox_roots[@]}"; do
        case "$requested_real" in
          "$sandbox_root"/*)
            sandbox_scope=1
            break 2
            ;;
        esac
      done
    done
  fi
  if [[ "$sandbox_scope" -eq 1 ]]; then
    echo "reap-lane: flock is required for destructive sandbox sweeps" >&2
    exit 2
  fi
fi

lock_path="$HOME/.reap-lane.lock"
lock_dir="${lock_path}.d"
lock_owner="${lock_dir}/owner"
lock_kind=""

release_sweep_lock() {
  local owner_pid="" owner_line=""
  case "$lock_kind" in
    flock)
      flock -u 9 >/dev/null 2>&1 || true
      exec 9>&-
      ;;
    mkdir)
      if [[ -f "$lock_owner" ]]; then
        IFS= read -r owner_line <"$lock_owner" || true
        case "$owner_line" in pid=*) owner_pid="${owner_line#pid=}" ;; esac
      fi
      if [[ "$owner_pid" == "$$" ]]; then
        rm -f "$lock_owner" >/dev/null 2>&1 || true
        rmdir "$lock_dir" >/dev/null 2>&1 || true
      fi
      ;;
  esac
  lock_kind=""
}

if command -v flock >/dev/null 2>&1; then
  exec 9>"$lock_path"
  if ! flock -n 9; then
    exec 9>&-
    echo "reap-lane: another reaper holds $lock_path" >&2
    exit 3
  fi
  lock_kind="flock"
else
  mkdir_lock_acquired=0
  stale_lock_dir=""
  recovery_claim=""
  if mkdir "$lock_dir" 2>/dev/null; then
    mkdir_lock_acquired=1
  else
    owner_pid=""
    if [[ -f "$lock_owner" ]]; then
      IFS= read -r owner_line <"$lock_owner" || true
      case "$owner_line" in pid=*) owner_pid="${owner_line#pid=}" ;; esac
    fi
    case "$owner_pid" in
      ''|*[!0-9]*) ;;
      *)
        # kill -0 also fails with EPERM for a live process owned by another
        # user. Only recover when both kill and ps say the PID is absent.
        if ! kill -0 "$owner_pid" 2>/dev/null &&
           command -v ps >/dev/null 2>&1 &&
           ! ps -p "$owner_pid" >/dev/null 2>&1; then
          recovery_claim="${lock_dir}/recovering"
          stale_lock_dir="${lock_dir}.stale.$$"
          # Claim the stale inode before renaming it. A contender delayed until
          # after the rename must re-read the replacement's owner and may not
          # move that new lock out from under its live holder.
          if mkdir "$recovery_claim" 2>/dev/null; then
            recovered_owner_pid=""
            if [[ -f "$lock_owner" ]]; then
              IFS= read -r owner_line <"$lock_owner" || true
              case "$owner_line" in pid=*) recovered_owner_pid="${owner_line#pid=}" ;; esac
            fi
            if [[ "$recovered_owner_pid" == "$owner_pid" ]] &&
               ! kill -0 "$recovered_owner_pid" 2>/dev/null &&
               command -v ps >/dev/null 2>&1 &&
               ! ps -p "$recovered_owner_pid" >/dev/null 2>&1 &&
               [[ ! -e "$stale_lock_dir" ]] &&
               mv "$lock_dir" "$stale_lock_dir" 2>/dev/null &&
               mkdir "$lock_dir" 2>/dev/null; then
              mkdir_lock_acquired=1
            else
              rmdir "$recovery_claim" >/dev/null 2>&1 || true
            fi
          fi
        fi
        ;;
    esac
  fi
  if [[ "$mkdir_lock_acquired" -ne 1 ]]; then
    echo "reap-lane: another reaper holds $lock_path" >&2
    exit 3
  fi
  if ! printf 'pid=%s\n' "$$" >"$lock_owner"; then
    rmdir "$lock_dir" >/dev/null 2>&1 || true
    echo "reap-lane: could not record lock owner for $lock_path" >&2
    exit 1
  fi
  lock_kind="mkdir"
fi
trap release_sweep_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

candidates=0
freshness_candidates=0
reaped=0
skipped=0
bytes_freed=0
grok_lane_lock_held=0
grok_lane_lock_path=""
grok_lane_lock_error=""
git_guard_error=""
# Dirty-tree classification for the lane most recently passed to
# has_blocking_dirty, plus the sweep-level triage accumulators.
dirty_category=""
dirty_tracked_count=0
dirty_untracked_count=0
dirty_tracked_sample=""
dirty_untracked_paths=""
triage_lock_only=0
triage_scratch=0
triage_tracked=0
triage_lock_only_lanes=""
triage_scratch_lanes=""
triage_tracked_lanes=""
triage_scratch_kib=0
triage_tracked_kib=0
triage_untracked_all=""
all_roots_missing=0
valid_all_roots=0

for all_root in ${all_roots[@]+"${all_roots[@]}"}; do
  if [[ ! -d "$all_root" ]]; then
    echo "reap-lane: --all root is not a directory: $all_root" >&2
    printf 'SKIP %s: --all root is not a directory\n' "$all_root"
    candidates=$((candidates + 1))
    skipped=$((skipped + 1))
    continue
  fi
  valid_all_roots=$((valid_all_roots + 1))
  shopt -s nullglob
  for cand in "$all_root"/*; do
    if [[ -d "$cand" ]]; then
      paths+=("$cand")
    fi
  done
  shopt -u nullglob
done
if [[ "${#all_roots[@]}" -gt 0 && "$valid_all_roots" -eq 0 ]]; then
  all_roots_missing=1
fi

# Every directory under $HOME that accumulates lane clones. [RES-07] a reclaimer
# whose scope does not match what grows is not a reclaimer: this list read
# `w3 uxw2 l1` (1.6G on the VM) while ~/w held 18G and ~/lanes 9.2G, and the
# disk reached 96% with the weekly cron reporting success throughout.
# The same failure then recurred one root later: the orchestrator creates every
# offload lane under ~/grok-sandbox, which this list still did not name -- 60G
# across 197 clones, disk at 92%, while the five listed roots had stopped
# growing. A root is added here when lanes start landing in it, not after the
# disk fills.
# Space-separated and overridable so a new lane root is a cron edit, not a code
# change. An override REPLACES the defaults -- narrowing the roots for a one-off
# sweep must not silently still reap the standing ones.
REAP_LANE_ROOTS="${REAP_LANE_ROOTS:-w3 uxw2 l1 w lanes grok-sandbox}"

REAP_GIT_NET_TIMEOUT_SEC="${REAP_GIT_NET_TIMEOUT_SEC:-120}"
case "$REAP_GIT_NET_TIMEOUT_SEC" in
  ''|*[!0-9]*|0)
    echo "reap-lane: REAP_GIT_NET_TIMEOUT_SEC must be a positive integer" >&2
    exit 2
    ;;
esac
if command -v timeout >/dev/null 2>&1; then
  git_net_has_timeout=1
else
  git_net_has_timeout=0
  echo "reap-lane: warning: timeout unavailable; git network calls are unbounded" >&2
fi

git_net() {
  if [[ "$git_net_has_timeout" -eq 1 ]]; then
    timeout "$REAP_GIT_NET_TIMEOUT_SEC" git "$@"
  else
    git "$@"
  fi
}

git_net_timed_out() {
  [[ "$1" -eq 124 || "$1" -eq 137 ]]
}

is_ignorable_path() {
  local p="${1#./}"
  case "$p" in
    .lane|.lane/*|.review|.review/*|VERDICT.md|REPORT.md|.venv|.venv/*|node_modules|node_modules/*|__pycache__|__pycache__/*|out|out/*)
      return 0
      ;;
  esac
  return 1
}

skip() {
  skipped=$((skipped + 1))
  printf 'SKIP %s: %s\n' "$1" "$2"
  # A destructive sandbox sweep takes its lane lock before eligibility. Keep
  # every refusal path fail-safe without requiring each newly added guard to
  # remember a bespoke unlock.
  release_grok_lane_lock
}

lane_label() {
  printf '%s\n' "${1#"${home_real}"/}"
}

lane_kib() {
  local kib
  kib="$(du -sk "$1" 2>/dev/null | awk '{print $1; exit}')"
  case "$kib" in ''|*[!0-9]*) kib=0 ;; esac
  printf '%s\n' "$kib"
}

# Skip a lane that has_blocking_dirty just refused, naming the category so the
# operator never has to re-derive it from `git status` by hand, and feed the
# sweep-level triage. Weekly sweeps on the VM refused ~30 lanes as a bare
# "dirty working tree"; every one of them fell into one of three mechanical
# buckets that took five shell round-trips to reconstruct.
skip_dirty() {
  local path="$1" real="$2" reason label kib
  if [[ -n "$git_guard_error" ]]; then
    skip "$path" "$git_guard_error"
    return 0
  fi
  label="$(lane_label "$real")"
  kib="$(lane_kib "$real")"
  case "$dirty_category" in
    untracked-scratch)
      reason="dirty working tree (untracked-scratch: ${dirty_untracked_count} files)"
      triage_scratch=$((triage_scratch + 1))
      triage_scratch_lanes="${triage_scratch_lanes}${label}"$'\n'
      triage_scratch_kib=$((triage_scratch_kib + kib))
      ;;
    *)
      reason="dirty working tree (tracked-edits: ${dirty_tracked_count} tracked, ${dirty_untracked_count} untracked; e.g.${dirty_tracked_sample})"
      triage_tracked=$((triage_tracked + 1))
      triage_tracked_lanes="${triage_tracked_lanes}${label}"$'\n'
      triage_tracked_kib=$((triage_tracked_kib + kib))
      ;;
  esac
  # Collapse to the first path component so a probe directory written into
  # several lanes is one shared entry rather than N distinct file paths.
  triage_untracked_all="${triage_untracked_all}$(printf '%s' "$dirty_untracked_paths" |
    awk -F/ 'NF > 1 { print $1 "/"; next } { print }' | LC_ALL=C sort -u)"$'\n'
  skip "$path" "$reason"
}

note_lock_only_reap() {
  if [[ "$dirty_category" == "lock-only" ]]; then
    triage_lock_only=$((triage_lock_only + 1))
    triage_lock_only_lanes="${triage_lock_only_lanes}$(lane_label "$1")"$'\n'
  fi
}

sorted_words() {
  printf '%s' "$1" | LC_ALL=C sort | tr '\n' ' ' | sed 's/ $//'
}

print_triage() {
  local shared shared_count
  if [[ $((triage_lock_only + triage_scratch + triage_tracked)) -eq 0 ]]; then
    return 0
  fi
  printf 'REAP TRIAGE dirty_skips=%s lock-only=%s untracked-scratch=%s tracked-edits=%s\n' \
    "$((triage_scratch + triage_tracked))" "$triage_lock_only" "$triage_scratch" "$triage_tracked"
  if [[ "$triage_lock_only" -gt 0 ]]; then
    printf 'REAP TRIAGE lock-only lanes=%s: %s\n' "$triage_lock_only" "$(sorted_words "$triage_lock_only_lanes")"
  fi
  if [[ "$triage_scratch" -gt 0 ]]; then
    printf 'REAP TRIAGE untracked-scratch lanes=%s held_bytes=%s: %s\n' \
      "$triage_scratch" "$((triage_scratch_kib * 1024))" "$(sorted_words "$triage_scratch_lanes")"
  fi
  if [[ "$triage_tracked" -gt 0 ]]; then
    printf 'REAP TRIAGE tracked-edits lanes=%s held_bytes=%s: %s\n' \
      "$triage_tracked" "$((triage_tracked_kib * 1024))" "$(sorted_words "$triage_tracked_lanes")"
  fi
  # An untracked path that recurs across skipped lanes is one scratch cluster
  # (a peer review wave writes the same probe files into every lane it
  # touches); name it once instead of per lane.
  shared="$(printf '%s' "$triage_untracked_all" | LC_ALL=C sort | uniq -c |
    awk '$1 >= 2 { sub(/^[[:space:]]*[0-9]+[[:space:]]/, ""); print }')"
  if [[ -n "$shared" ]]; then
    shared_count="$(printf '%s\n' "$shared" | wc -l | tr -d ' ')"
    printf 'REAP TRIAGE shared_untracked paths=%s: %s\n' "$shared_count" "$(sorted_words "$shared"$'\n')"
  fi
}

path_mtime() {
  local mtime
  mtime="$(stat -c %Y "$1" 2>/dev/null)" || mtime="$(stat -f %m "$1" 2>/dev/null)" || return 1
  case "$mtime" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$mtime"
}

path_inode() {
  local inode
  inode="$(stat -L -c %i "$1" 2>/dev/null)" ||
    inode="$(stat -L -f %i "$1" 2>/dev/null)" || return 1
  case "$inode" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$inode"
}

is_grok_sandbox() {
  local sandbox_root
  for sandbox_root in "${sandbox_roots[@]}"; do
    case "$1" in
      "$sandbox_root"/*) return 0 ;;
    esac
  done
  return 1
}

# Apply the same marker/lease/TTL contract as scripts/remote_agent.sh. Returns
# success only after the sandbox is old and unoccupied; deletion still takes
# the per-lane lock immediately before archive/anchor and holds it through rm.
grok_sandbox_is_stale() {
  local real="$1" path="$2" root key marker lease ttl now mtime issued expiry lease_line
  root="$(dirname "$real")"
  key="${real##*/}"
  marker="$real/.workbay-lane-sandbox"
  lease="$root/.lane-live-$key"
  ttl="${WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC:-172800}"
  case "$ttl" in
    ''|*[!0-9]*)
      skip "$path" "invalid sandbox TTL"
      return 1
      ;;
    0)
      skip "$path" "sandbox TTL reaping is disabled"
      return 1
      ;;
  esac

  if [[ ! -f "$marker" ]]; then
    freshness_candidates=$((freshness_candidates + 1))
    skip "$path" "unmarked sandbox dir; operator review"
    return 1
  else
    mtime="$(path_mtime "$marker" || true)"
    now="$(date +%s)"
    if [[ -z "$mtime" ]]; then
      skip "$path" "could not read sandbox marker age"
      return 1
    fi
    if [[ $((now - mtime)) -le "$ttl" ]]; then
      skip "$path" "sandbox marker has not reached TTL"
      return 1
    fi
  fi

  if [[ -f "$lease" ]]; then
    issued=""
    expiry=""
    while IFS= read -r lease_line || [[ -n "$lease_line" ]]; do
      case "$lease_line" in
        issued=*) issued="${lease_line#issued=}" ;;
        expiry=*) expiry="${lease_line#expiry=}" ;;
      esac
    done <"$lease" || {
      skip "$path" "sandbox lease is live or unreadable"
      return 1
    }
    case "$issued" in
      ''|*[!0-9]*)
        skip "$path" "sandbox lease is live or malformed"
        return 1
        ;;
    esac
    case "$expiry" in
      ''|*[!0-9]*)
        skip "$path" "sandbox lease is live or malformed"
        return 1
        ;;
    esac
    if [[ "$now" -lt "$expiry" ]]; then
      skip "$path" "sandbox lease is live"
      return 1
    fi
  fi
  return 0
}

acquire_grok_lane_lock() {
  local real="$1" root key lane_lock lane_lock_inode fd_inode lock_status
  grok_lane_lock_error=""
  is_grok_sandbox "$real" || return 0
  root="$(dirname "$real")"
  key="${real##*/}"
  lane_lock="$root/.lane-lock-$key"
  if ! command -v flock >/dev/null 2>&1; then
    grok_lane_lock_error="lane lock unverifiable: flock unavailable"
    return 1
  fi
  # Create-or-open the stable materializer lock path, then lock and verify the
  # inode. Treating absence as unlocked leaves no fd against which to detect a
  # path materialized during the final deletion window.
  if ! exec 8>>"$lane_lock"; then
    grok_lane_lock_error="lane lock unverifiable: could not open lock path"
    return 1
  fi
  if flock -n 8; then
    :
  else
    lock_status=$?
    exec 8>&-
    if [[ "$lock_status" -eq 1 ]]; then
      grok_lane_lock_error="lane lock contended"
    else
      grok_lane_lock_error="lane lock unverifiable: flock failed with status $lock_status"
    fi
    return 1
  fi
  # Do not use `-ef` here: macOS gives /dev/fd/8 the devfs device id even when
  # it represents this open inode. The path and fd are on the same filesystem,
  # so equal inode numbers provide the replacement check we need.
  lane_lock_inode="$(path_inode "$lane_lock")" || {
    exec 8>&-
    grok_lane_lock_error="lane lock unverifiable: could not stat lock path"
    return 1
  }
  fd_inode="$(path_inode /dev/fd/8)" || {
    exec 8>&-
    grok_lane_lock_error="lane lock unverifiable: could not stat open lock fd"
    return 1
  }
  if [[ "$lane_lock_inode" != "$fd_inode" ]]; then
    exec 8>&-
    grok_lane_lock_error="lane lock replaced"
    return 1
  fi
  grok_lane_lock_held=1
  grok_lane_lock_path="$lane_lock"
  return 0
}

grok_lane_lock_matches() {
  local real="$1" lane_lock_inode fd_inode
  grok_lane_lock_error=""
  is_grok_sandbox "$real" || return 0
  if [[ "$grok_lane_lock_held" -ne 1 || -z "$grok_lane_lock_path" ||
        ! -e "$grok_lane_lock_path" ]]; then
    grok_lane_lock_error="lane lock replaced"
    return 1
  fi
  lane_lock_inode="$(path_inode "$grok_lane_lock_path")" || {
    grok_lane_lock_error="lane lock unverifiable: could not stat lock path"
    return 1
  }
  fd_inode="$(path_inode /dev/fd/8)" || {
    grok_lane_lock_error="lane lock unverifiable: could not stat open lock fd"
    return 1
  }
  if [[ "$lane_lock_inode" != "$fd_inode" ]]; then
    grok_lane_lock_error="lane lock replaced"
    return 1
  fi
  return 0
}

cleanup_grok_sandbox_siblings() {
  local real="$1" root key
  is_grok_sandbox "$real" || return 0
  root="$(dirname "$real")"
  key="${real##*/}"
  # The materializer owns the lock path. Unlinking it while fd 8 still holds
  # the old inode lets a concurrent materializer create and lock a fresh inode
  # that this cleanup can then remove. Leave the stable lock path in place;
  # only checkout-owned siblings are stale after the lane is removed.
  rm -rf -- "$root/.lane-live-$key" "$root/.venv-lane-$key" \
    "$root/.venv-sync-stamp-$key"
}

release_grok_lane_lock() {
  if [[ "$grok_lane_lock_held" -eq 1 ]]; then
    flock -u 8 >/dev/null 2>&1 || true
    exec 8>&-
    grok_lane_lock_held=0
    grok_lane_lock_path=""
  fi
}

# $1 = a realpath already known to be under $home_real.
# True when it is a lane *inside* one of the allowlisted roots. Matching is on
# whole path segments, not a substring: `*/w/*` would also admit ~/work and
# ~/wp-content, and the roots exist to bound what `rm -rf` can reach.
# The root itself is refused -- reaping ~/w would take every lane with it.
is_under_lane_root() {
  local rel="${1#"${home_real}"/}" first root
  if [[ -n "$remote_agent_root_real" ]]; then
    case "$1" in
      "$remote_agent_root_real"/*) return 0 ;;
    esac
  fi
  [[ "$rel" == */* ]] || return 1
  first="${rel%%/*}"
  for root in $REAP_LANE_ROOTS; do
    [[ "$first" == "$root" ]] && return 0
  done
  return 1
}

partial_intent_path_for() {
  local key
  key="$(printf '%s' "$1" | git hash-object --stdin)" || return 1
  printf '%s/partial/%s.json\n' "${REAP_STATE_DIR:-$HOME/.workbay-reap}" "$key"
}

json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

write_partial_intent() {
  local lane_path="$1" archive_ref="$2" verified_tip="$3" intent tmp intent_dir
  intent="$(partial_intent_path_for "$lane_path")" || return 1
  intent_dir="$(dirname "$intent")"
  mkdir -p "$intent_dir" || return 1
  tmp="${intent}.tmp.$$"
  if ! printf '{"lane_path":"%s","archive_ref":"%s","verified_tips":["%s"],"recorded_at":"%s"}\n' \
      "$(json_escape "$lane_path")" "$(json_escape "$archive_ref")" \
      "$(json_escape "$verified_tip")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$tmp"; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    return 1
  fi
  if ! mv "$tmp" "$intent"; then
    rm -f "$tmp" >/dev/null 2>&1 || true
    return 1
  fi
  partial_intent_path="$intent"
}

has_unmerged_work() {
  local dir="$1" upstream="$2" ref rev head_rev refs_output reflog_output reflog_selector
  refs_output="$(git -C "$dir" for-each-ref --format='%(refname)' refs)" || return 0
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    # Stashes have a stronger content-aware guard below. In particular, a
    # stash containing only disposable lane metadata is intentionally allowed.
    [[ "$ref" == "refs/stash" ]] && continue
    # A ref to a non-commit cannot be proven recoverable from the upstream
    # commit graph. Annotated tags are peeled to the commit they retain.
    rev="$(git -C "$dir" rev-parse --verify --quiet "${ref}^{commit}")" || return 0
    if ! git -C "$dir" merge-base --is-ancestor "$rev" "$upstream"; then
      return 0
    fi
  done <<<"$refs_output"
  head_rev="$(git -C "$dir" rev-parse HEAD)"
  if ! git -C "$dir" merge-base --is-ancestor "$head_rev" "$upstream"; then
    return 0
  fi
  reflog_output="$(git -C "$dir" reflog --all --format='%gD %H')" || return 0
  while IFS= read -r ref; do
    [[ -z "$ref" ]] && continue
    reflog_selector="${ref% *}"
    case "$reflog_selector" in refs/stash@\{*\}) continue ;; esac
    rev="${ref##* }"
    if ! git -C "$dir" merge-base --is-ancestor "$rev" "$upstream"; then
      return 0
    fi
  done <<<"$reflog_output"
  return 1
}

has_blocking_dirty() {
  local dir="$1" line entry left right status_output xy
  local tracked=0 untracked=0 lock_mod=0 manifest_dirty=0 sample="" sample_n=0 untracked_paths=""
  git_guard_error=""
  dirty_category=""
  dirty_tracked_count=0
  dirty_untracked_count=0
  dirty_tracked_sample=""
  dirty_untracked_paths=""
  # -uall: an untracked directory would otherwise collapse to one entry and
  # the triage count would understate a scratch cluster.
  if ! status_output="$(git -C "$dir" status --porcelain -uall)"; then
    git_guard_error="could not read git status"
    return 0
  fi
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    xy="${line:0:2}"
    entry="${line:3}"
    if [[ "$entry" == *" -> "* ]]; then
      left="${entry%% -> *}"
      right="${entry#* -> }"
      if is_ignorable_path "$left" && is_ignorable_path "$right"; then
        continue
      fi
      entry="$right"
    elif is_ignorable_path "$entry"; then
      continue
    elif [[ "$xy" == "??" ]]; then
      untracked=$((untracked + 1))
      untracked_paths="${untracked_paths}${entry}"$'\n'
      continue
    fi
    tracked=$((tracked + 1))
    case "${entry##*/}" in
      pyproject.toml) manifest_dirty=1 ;;
      uv.lock)
        # Only an in-place modification is churn. A deleted, added, or renamed
        # lock is a change of intent and stays a tracked edit.
        case "$xy" in " M"|"M "|"MM") lock_mod=$((lock_mod + 1)) ;; esac
        ;;
    esac
    if [[ "$sample_n" -lt 3 ]]; then
      sample="${sample} ${entry}"
      sample_n=$((sample_n + 1))
    fi
  done <<<"$status_output"
  dirty_tracked_count="$tracked"
  dirty_untracked_count="$untracked"
  dirty_tracked_sample="$sample"
  dirty_untracked_paths="$untracked_paths"
  if [[ "$tracked" -eq 0 && "$untracked" -eq 0 ]]; then
    return 1
  fi
  # lock-only: every non-ignorable entry is a modified uv.lock and no manifest
  # moved. The lock is a derived artifact of a clean pyproject.toml, so `uv
  # lock` recreates it; 76 of the first sweep's ~90 dirty lanes were exactly
  # this one-line version bump.
  if [[ "$untracked" -eq 0 && "$manifest_dirty" -eq 0 && "$lock_mod" -eq "$tracked" ]]; then
    # Counted by note_lock_only_reap once the lane actually reaps: a later
    # guard (stash, snapshot drift, rm failure) can still refuse it, and the
    # triage must only list lanes whose churn was in fact ignored.
    dirty_category="lock-only"
    return 1
  fi
  if [[ "$tracked" -eq 0 ]]; then
    dirty_category="untracked-scratch"
  else
    dirty_category="tracked-edits"
  fi
  return 0
}

stash_has_real_work() {
  local dir="$1" sha f git_status stash_output tree_output
  git_guard_error=""
  if git -C "$dir" rev-parse --verify --quiet refs/stash >/dev/null; then
    :
  else
    git_status=$?
    if [[ "$git_status" -eq 1 ]]; then
      return 1
    fi
    git_guard_error="could not read git status"
    return 0
  fi
  if ! stash_output="$(git -C "$dir" stash list --format='%H')"; then
    git_guard_error="could not read git status"
    return 0
  fi
  while IFS= read -r sha; do
    [[ -z "$sha" ]] && continue
    if git -C "$dir" diff --quiet "${sha}^1" "$sha"; then
      :
    else
      git_status=$?
      if [[ "$git_status" -eq 1 ]]; then
        return 0
      fi
      git_guard_error="could not read git status"
      return 0
    fi
    if git -C "$dir" rev-parse --verify --quiet "${sha}^3" >/dev/null; then
      if ! tree_output="$(git -C "$dir" ls-tree -r --name-only "${sha}^3")"; then
        git_guard_error="could not read git status"
        return 0
      fi
      while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        if ! is_ignorable_path "$f"; then
          return 0
        fi
      done <<<"$tree_output"
    else
      git_status=$?
      if [[ "$git_status" -ne 1 ]]; then
        git_guard_error="could not read git status"
        return 0
      fi
    fi
  done <<<"$stash_output"
  return 1
}

# Print the complete deletion-safety state that can change independently of
# the checkout files. The optional second argument excludes the one ref this
# reaper creates when anchoring a linked worktree's detached HEAD.
lane_safety_snapshot() {
  local dir="$1" ignored_ref="${2:-}" head_ref head_sha ref_line
  local refs_output reflog_output stash_output status_output
  head_ref="$(git -C "$dir" symbolic-ref --quiet HEAD 2>/dev/null || printf 'DETACHED')" || return 1
  head_sha="$(git -C "$dir" rev-parse --verify HEAD)" || return 1
  refs_output="$(git -C "$dir" for-each-ref --format='%(refname) %(objectname)' refs)" || return 1
  # HEAD and refs can return to their original values after a writer commits
  # and resets. The sorted unique reflog object IDs make that otherwise hidden
  # mutation part of the deletion-safety state.
  reflog_output="$(git -C "$dir" reflog --all --format='%H' | LC_ALL=C sort -u)" || return 1
  stash_output="$(git -C "$dir" stash list --format='%H %gd')" || return 1
  status_output="$(git -C "$dir" status --porcelain=v1 -uall)" || return 1
  printf 'HEAD %s %s\n' "$head_ref" "$head_sha" || return 1
  printf '%s\n' REFS
  while IFS= read -r ref_line; do
    [[ -z "$ref_line" ]] && continue
    [[ "${ref_line%% *}" == "$ignored_ref" ]] && continue
    printf '%s\n' "$ref_line"
  done <<<"$refs_output"
  printf '%s\n' REFLOG
  printf '%s\n' "$reflog_output"
  printf '%s\n' STASH
  printf '%s\n' "$stash_output"
  printf '%s\n' STATUS
  printf '%s\n' "$status_output"
}

lane_matches_snapshot() {
  local dir="$1" ignored_ref="$2" expected="$3" actual
  actual="$(lane_safety_snapshot "$dir" "$ignored_ref")" || return 1
  [[ "$actual" == "$expected" ]]
}

# Push every commit a lane holds into the keep-repo, then prove it landed.
# $1 = lane realpath, $2 = ref namespace (the lane's path under $HOME).
#
# This is what makes reaping safe on a wave that merged by squash or rebase: the
# lane's commits are never ancestors of main, so ancestry can only ever say
# "unmerged" and the reclaimer frees nothing. Once the commits are in the
# archive, deleting the working tree cannot lose work regardless of whether it
# ever reached main -- and the checkout is where the space actually is (on the
# VM: 239M of shared git objects against ~500M of checkout per lane).
#
# Not --force: these refs may be the only copy of that lane's history. A
# diverged re-archive preserves its incoming tip under an immutable
# sha-keyed supersession ref rather than overwriting the earlier copy.
archive_error=""

set_archive_error_tail() {
  local prefix="$1" diagnostic="$2" tail_line
  tail_line="$(printf '%s\n' "$diagnostic" | tail -n 8 | tr '\n' ' ' |
    sed 's/[[:space:]]*$//')"
  archive_error="${prefix}: ${tail_line:-no diagnostic}"
}

set_archive_push_error() {
  local diagnostic="$1"
  case "$diagnostic" in
    *non-fast-forward*|*fetch\ first*|*already\ exists*|*would\ clobber*)
      set_archive_error_tail "archive ref exists with different tip (non-force)" "$diagnostic"
      ;;
    *) set_archive_error_tail "archive push failed" "$diagnostic" ;;
  esac
}

archive_lane() {
  local dir="$1" ns="$2" head_sha want="" verify_want="" got ref sha source_ref
  local command_output existing_output existing_sha ancestry_status net_status refs_output
  local destination superseded_ref short_sha
  local push_specs=()
  archive_error=""
  archive_head_ref=""
  if ! git -C "$dir" rev-parse --verify --quiet HEAD >/dev/null; then
    archive_error="archive preparation failed: could not read HEAD"
    return 1
  fi
  # Keep the historical branch namespace for consumers, plus an unambiguous
  # refs/ mirror that retains tags, notes, replacement refs, and any other
  # local ref without flattening unlike kinds onto one destination.
  if ! refs_output="$(git -C "$dir" for-each-ref --format='%(refname) %(objectname)' refs)"; then
    archive_error="ref enumeration failed: could not enumerate local refs"
    return 1
  fi
  while IFS=' ' read -r source_ref sha; do
    [[ -z "$source_ref" ]] && continue
    case "$source_ref" in
      refs/heads/*)
        destination="refs/lanes/${ns}/${source_ref#refs/heads/}"
        want="${want}${destination} ${sha}"$'\n'
        ;;
    esac
    destination="refs/lanes/${ns}/refs/${source_ref#refs/}"
    want="${want}${destination} ${sha}"$'\n'
  done <<<"$refs_output"
  head_sha="$(git -C "$dir" rev-parse HEAD)" || {
    archive_error="archive preparation failed: could not read HEAD"
    return 1
  }
  want="${want}refs/lanes/${ns}/HEAD ${head_sha}"$'\n'

  # Diagnose immutable-ref conflicts before push. A failed probe is not by
  # itself fatal: the push supplies the authoritative transport diagnostic.
  if existing_output="$(git_net ls-remote -- "$archive_to" "refs/lanes/${ns}/*" 2>&1)"; then
    got="$(printf '%s\n' "$existing_output" | awk '{ print $2, $1 }')"
  else
    net_status=$?
    if git_net_timed_out "$net_status"; then
      archive_error="archive transport timed out"
      return 1
    fi
    got=""
  fi

  while IFS=' ' read -r ref sha; do
    [[ -z "$ref" ]] && continue
    existing_sha="$(printf '%s\n' "$got" | awk -v wanted="$ref" '$1 == wanted { print $2; exit }')"
    if [[ -n "$existing_sha" && "$existing_sha" != "$sha" ]]; then
      if git -C "$dir" merge-base --is-ancestor "$existing_sha" "$sha" 2>/dev/null; then
        : # A normal retry may advance a previously archived ref.
      else
        ancestry_status=$?
        if [[ "$ancestry_status" -eq 1 ]]; then
          short_sha="${sha:0:12}"
          superseded_ref="refs/archive/${ns}/superseded/${short_sha}"
          if command_output="$(git_net -C "$dir" push --quiet --no-verify -- \
              "$archive_to" "${sha}:${superseded_ref}" 2>&1)"; then
            :
          else
            net_status=$?
            if git_net_timed_out "$net_status"; then
              archive_error="archive transport timed out"
            else
              set_archive_push_error "$command_output"
            fi
            return 1
          fi
          if command_output="$(git_net ls-remote -- "$archive_to" "$superseded_ref" 2>&1)"; then
            :
          else
            net_status=$?
            if git_net_timed_out "$net_status"; then
              archive_error="archive transport timed out"
            else
              set_archive_error_tail "archive verification failed" "$command_output"
            fi
            return 1
          fi
          if ! printf '%s\n' "$command_output" | awk -v sha="$sha" -v ref="$superseded_ref" \
              '$1 == sha && $2 == ref { found = 1 } END { exit !found }'; then
            archive_error="archive verification failed: missing or mismatched ${superseded_ref}"
            return 1
          fi
          # The primary immutable ref remains on its previous tip; both sides
          # are now durable, so this generation no longer wedges reclamation.
          verify_want="${verify_want}${ref} ${existing_sha}"$'\n'
          if [[ "$ref" == "refs/lanes/${ns}/HEAD" ]]; then
            archive_head_ref="$superseded_ref"
          fi
          continue
        fi
        # If the existing object is not local, let push decide and capture its
        # authoritative non-fast-forward or transport diagnostic.
      fi
    fi
    push_specs+=("${sha}:${ref}")
    verify_want="${verify_want}${ref} ${sha}"$'\n'
  done <<<"$want"

  if [[ ${#push_specs[@]} -gt 0 ]]; then
    if command_output="$(git_net -C "$dir" push --quiet --no-verify -- "$archive_to" \
        "${push_specs[@]}" 2>&1)"; then
      :
    else
      net_status=$?
      if git_net_timed_out "$net_status"; then
        archive_error="archive transport timed out"
      else
        set_archive_push_error "$command_output"
      fi
      return 1
    fi
  fi

  # Read the refs back out of the archive. A push that reported success but
  # landed nothing would otherwise be indistinguishable from one that worked,
  # and the next step is rm -rf.
  if command_output="$(git_net ls-remote -- "$archive_to" "refs/lanes/${ns}/*" 2>&1)"; then
    :
  else
    net_status=$?
    if git_net_timed_out "$net_status"; then
      archive_error="archive transport timed out"
    else
      set_archive_error_tail "archive verification failed" "$command_output"
    fi
    return 1
  fi
  got="$(printf '%s\n' "$command_output" | awk '{ print $2, $1 }')"
  while IFS=' ' read -r ref sha; do
      [[ -z "$ref" ]] && continue
    if ! printf '%s\n' "$got" | grep -qxF "$ref $sha"; then
      archive_error="archive verification failed: missing or mismatched ${ref}"
      return 1
    fi
  done <<<"$verify_want"
  return 0
}

# Preserve commits named by a reflog but unreachable from every current ref.
# The lane owns those reflogs; rm would otherwise remove their only names.
archive_reflog_only_commits() {
  local dir="$1" ns="$2" reachable reflog_output got sha ref command_output net_status
  local reflog_shas=() ref_specs=()
  reachable="$(git -C "$dir" rev-list --all)" || return 1
  reflog_output="$(git -C "$dir" reflog --all --format='%H' | LC_ALL=C sort -u)" || return 1
  while IFS= read -r sha; do
    [[ -z "$sha" ]] && continue
    if ! printf '%s\n' "$reachable" | grep -qxF "$sha"; then
      reflog_shas+=("$sha")
      ref="refs/reaped/${ns}/reflog/${sha}"
      ref_specs+=("${sha}:${ref}")
    fi
  done <<<"$reflog_output"
  [[ ${#ref_specs[@]} -gt 0 ]] || return 0
  if command_output="$(git_net -C "$dir" push --quiet --no-verify -- "$archive_to" \
      "${ref_specs[@]}" 2>&1)"; then
    :
  else
    net_status=$?
    if git_net_timed_out "$net_status"; then archive_error="archive transport timed out"
    else set_archive_push_error "$command_output"; fi
    return 1
  fi
  if command_output="$(git_net ls-remote -- "$archive_to" "refs/reaped/${ns}/reflog/*" 2>&1)"; then
    :
  else
    net_status=$?
    if git_net_timed_out "$net_status"; then archive_error="archive transport timed out"
    else set_archive_error_tail "archive verification failed" "$command_output"; fi
    return 1
  fi
  got="$(printf '%s\n' "$command_output" | awk '{ print $2, $1 }')"
  for sha in "${reflog_shas[@]}"; do
    ref="refs/reaped/${ns}/reflog/${sha}"
    if ! printf '%s\n' "$got" | grep -qxF "$ref $sha"; then
      archive_error="archive verification failed: missing or mismatched ${ref}"
      return 1
    fi
  done
  return 0
}

# Echo the main worktree of a linked worktree; fail if $1 is not one.
# A linked worktree's .git is a file pointing into <parent>/.git/worktrees/<n>.
lane_parent_repo() {
  local dir="$1" common
  [[ -f "$dir/.git" ]] || return 1
  common="$(git -C "$dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  dirname "$common"
}

# True when $1 is a main worktree with linked worktrees hanging off it.
# On the VM three such repos sit inside lane roots -- ~/l1/r7-int alone is
# parent to 28 lanes -- and reaping one takes the refs and the shared object
# store every one of its worktrees depends on.
has_linked_worktrees() {
  local dir="$1" n
  n="$(git -C "$dir" worktree list --porcelain 2>/dev/null | grep -c '^worktree ' || true)"
  [[ "${n:-0}" -gt 1 ]]
}

live_probe_reason=""
restore_quarantined_error=""

# Return 0 = occupied, 1 = provably unoccupied, 2 = could not determine.
# Archive-mode sweeps of ~/w, ~/lanes, etc. have no lease/lock contract, so a
# worker that committed >1h ago and is now running a long test would otherwise
# lose its checkout (VMREAP-RA-06). Keep the three outcomes separate: the
# fail-closed unknown branch addresses ISSUEDAG-1-HARM-04/HARNC-R-10 and keeps
# restricted or absent process enumeration from becoming permission to delete.
lane_has_live_process() {
  # REAP_LIVE_PROBE is a hermetic seam for the no-probe case. It also makes it
  # possible to force a particular portable probe when validating a host whose
  # procfs is restricted (ISSUEDAG-1-HARNC-R-06/GATES-HARNESS-R-10).
  local dir="$1" probe="${REAP_LIVE_PROBE:-auto}" cwd target pid self_cwd
  local proc_error=0 self_target="" procfs_restricted=0
  local mount_source mount_point mount_type mount_options mount_extra
  live_probe_reason=""
  if [[ -z "$dir" ]]; then
    live_probe_reason="could not determine lane liveness: empty lane path"
    return 2
  fi

  case "$probe" in
    none)
      live_probe_reason="could not determine lane liveness: process probe disabled"
      return 2
      ;;
    ''|auto|proc)
      if [[ ! -d /proc ]]; then
        if [[ "$probe" == "proc" ]]; then
          live_probe_reason="could not determine lane liveness: procfs is unavailable"
          return 2
        fi
      else
        # A hidepid mount deliberately hides other users' processes. The
        # current shell remains visible, but that is not enough to prove a lane
        # is unoccupied, so let the portable fallback have a chance instead.
        if [[ -r /proc/mounts ]]; then
          while IFS=' ' read -r mount_source mount_point mount_type mount_options mount_extra; do
            [[ "$mount_point" == "/proc" ]] || continue
            case ",${mount_options}," in
              *,hidepid=1,*|*,hidepid=2,*)
                procfs_restricted=1
                break
                ;;
            esac
          done </proc/mounts
        fi
        if [[ "$procfs_restricted" -eq 1 ]]; then
          if [[ "$probe" == "proc" ]]; then
            live_probe_reason="could not determine lane liveness: procfs enumeration is restricted"
            return 2
          fi
        else
          self_cwd="/proc/$$/cwd"
          if [[ ! -L "$self_cwd" ]] || ! self_target="$(readlink "$self_cwd" 2>/dev/null)"; then
            if [[ "$probe" == "proc" ]]; then
              live_probe_reason="could not determine lane liveness: procfs cwd entries are unreadable"
              return 2
            fi
          else
            for cwd in /proc/[0-9]*/cwd; do
              [[ -L "$cwd" ]] || continue
              pid="${cwd#/proc/}"
              pid="${pid%/cwd}"
              target="$(readlink "$cwd" 2>/dev/null || true)"
              if [[ -z "$target" ]]; then
                # Processes can disappear between glob expansion and readlink;
                # an entry that still exists is an enumeration failure.
                if [[ -e "${cwd%/cwd}" ]]; then
                  proc_error=1
                fi
                continue
              fi
              case "$target" in
                "$dir"|"$dir"/*|"$dir (deleted)"|"$dir"/*\ \(deleted\))
                  [[ "$pid" == "$$" ]] && continue
                  live_probe_reason="lane has a live process"
                  return 0
                  ;;
              esac
            done
            if [[ "$proc_error" -eq 0 ]]; then
              live_probe_reason="lane has no live process"
              return 1
            fi
            if [[ "$probe" == "proc" ]]; then
              live_probe_reason="could not determine lane liveness: procfs cwd enumeration failed"
              return 2
            fi
          fi
        fi
      fi
      ;;
    lsof)
      ;;
    *)
      live_probe_reason="could not determine lane liveness: invalid REAP_LIVE_PROBE=$probe"
      return 2
      ;;
  esac

  if [[ "$probe" == "none" ]]; then
    live_probe_reason="could not determine lane liveness: process probe disabled"
    return 2
  fi

  if command -v lsof >/dev/null 2>&1; then
    if lsof -a -d cwd -- "$dir" >/dev/null 2>&1; then
      live_probe_reason="lane has a live process"
      return 0
    fi
    case "$?" in
      1)
        live_probe_reason="lane has no live process"
        return 1
        ;;
      *)
        live_probe_reason="could not determine lane liveness: lsof failed"
        return 2
        ;;
    esac
  fi

  if command -v fuser >/dev/null 2>&1; then
    if fuser -m "$dir" >/dev/null 2>&1; then
      live_probe_reason="lane has a live process"
      return 0
    fi
    case "$?" in
      1)
        live_probe_reason="lane has no live process"
        return 1
        ;;
      *)
        live_probe_reason="could not determine lane liveness: fuser failed"
        return 2
        ;;
    esac
  fi

  live_probe_reason="could not determine lane liveness: no process probe is available"
  return 2
}

# Treat both an observed process and an unknown result as occupied. Callers use
# this wrapper at every destructive boundary so no probe can fail open.
lane_live_probe_blocks_reap() {
  local status
  if lane_has_live_process "$1"; then
    status=0
  else
    status=$?
  fi
  case "$status" in
    1) return 1 ;;
    *) return 0 ;;
  esac
}

# Move $1 aside so new workers cannot enter the original path. Same-filesystem
# rename is atomic; a worker whose cwd is already inside follows the inode.
# Prints the quarantine path on success. Hidden so --all's `$root/*` glob does
# not pick the aside copy up as a fresh lane.
quarantine_lane() {
  local real="$1" parent key dest
  parent="$(dirname "$real")"
  key="${real##*/}"
  dest="$parent/.reap-quarantine-${key}.$$"
  if [[ -e "$dest" || -L "$dest" ]]; then
    return 1
  fi
  mv -- "$real" "$dest" || return 1
  printf '%s\n' "$dest"
}

restore_quarantined_lane() {
  local real="$1" quarantine="$2"
  restore_quarantined_error=""
  if [[ -e "$real" || -L "$real" ]]; then
    restore_quarantined_error="destination already exists: $real"
    return 1
  fi
  if [[ ! -e "$quarantine" && ! -L "$quarantine" ]]; then
    restore_quarantined_error="quarantine does not exist: $quarantine"
    return 1
  fi
  if ! mv -- "$quarantine" "$real"; then
    restore_quarantined_error="could not move quarantine back to $real"
    return 1
  fi
}

lane_newest_mtime() {
  local dir="$1" newest=0 candidate candidate_mtime git_item
  candidate_mtime="$(path_mtime "$dir" || true)"
  [[ -n "$candidate_mtime" ]] || return 1
  [[ "$candidate_mtime" -gt "$newest" ]] && newest="$candidate_mtime"
  for git_item in index HEAD; do
    candidate="$(git -C "$dir" rev-parse --path-format=absolute --git-path "$git_item" 2>/dev/null)" || return 1
    candidate_mtime="$(path_mtime "$candidate" || true)"
    [[ -n "$candidate_mtime" ]] || return 1
    [[ "$candidate_mtime" -gt "$newest" ]] && newest="$candidate_mtime"
  done
  printf '%s\n' "$newest"
}

archive_generation() {
  local dir="$1"
  git -C "$dir" rev-list --max-parents=0 HEAD 2>/dev/null |
    LC_ALL=C sort | sed -n '1p'
}

# Anchor a linked worktree's HEAD as a real ref in its parent.
# A worktree shares the parent's ref store, so its branches already survive
# removal -- but a detached HEAD is held only by the worktree's own HEAD file,
# which `git worktree prune` deletes. Without this the commit becomes
# unreachable and the next gc drops it.
anchor_worktree_head() {
  local dir="$1" ns="$2" parent="$3" head_sha
  head_sha="$(git -C "$dir" rev-parse --verify --quiet HEAD)" || return 1
  git -C "$dir" update-ref "refs/lanes/${ns}/HEAD" "$head_sha" || return 1
  # Read back from the parent, not from the worktree: git keeps some namespaces
  # (refs/bisect, refs/worktree, refs/rewritten) per-worktree, and a ref that
  # only ever existed in the worktree's own ref store dies with `worktree
  # prune` -- taking the commit with it. refs/lanes is not one of those today,
  # which is exactly why this is worth asserting rather than assuming.
  [[ "$(git -C "$parent" rev-parse --verify --quiet "refs/lanes/${ns}/HEAD")" == "$head_sha" ]]
}

# Return 0 = skip or reaped (normal); 1 = internal error.
process_one() {
  local path="$1"
  local real size size_kib head_sha upstream upstream_label url ref log_dir ns parent
  local now newest_mtime min_age generation cleanup_failed=0
  local safety_snapshot safety_ignore_ref="" archive_ref="" partial_archive_ref="" partial_line
  local intent_real="" partial_intent_path="" net_status restore_error=""
  local partial_verified_tips="" occupant_head="" stale_intent quarantine=""

  candidates=$((candidates + 1))
  dirty_category=""

  intent_real="$(realpath "$path" 2>/dev/null || true)"
  if [[ -n "$intent_real" ]]; then
    partial_intent_path="$(partial_intent_path_for "$intent_real" 2>/dev/null || true)"
  fi
  if [[ -n "$partial_intent_path" && -f "$partial_intent_path" ]]; then
    partial_archive_ref="$(sed -n 's/.*"archive_ref":"\([^"]*\)".*/\1/p' \
      "$partial_intent_path" | sed -n '1p')"
    partial_verified_tips="$(sed -n 's/.*"verified_tips":\[\([^]]*\)\].*/\1/p' \
      "$partial_intent_path" | sed -n '1p')"
    occupant_head="$(git -C "$path" rev-parse --verify --quiet HEAD 2>/dev/null || true)"
    if [[ -n "$occupant_head" && -n "$partial_verified_tips" \
        && "$partial_verified_tips" != *"\"${occupant_head}\""* ]]; then
      # The damaged checkout is gone: a fresh occupant at a tip the intent
      # never verified is a new lane, so the sentinel must not block it forever.
      stale_intent="${partial_intent_path}.stale.$(date -u +%Y%m%dT%H%M%SZ)"
      if mv "$partial_intent_path" "$stale_intent"; then
        echo "reap-lane: warning: stale partial intent superseded by new occupant ${occupant_head}; kept at ${stale_intent}" >&2
      else
        skip "$path" "stale partial intent could not be retired: ${partial_intent_path}"
        return 0
      fi
    else
      freshness_candidates=$((freshness_candidates + 1))
      skip "$path" "partial reap after archive ${partial_archive_ref:-unknown}; operator review (intent: ${partial_intent_path})"
      return 0
    fi
  elif [[ -f "$path/.workbay-reap-partial" ]]; then
    while IFS= read -r partial_line || [[ -n "$partial_line" ]]; do
      case "$partial_line" in
        archive_ref=*) partial_archive_ref="${partial_line#archive_ref=}"; break ;;
      esac
    done <"$path/.workbay-reap-partial" || true
    freshness_candidates=$((freshness_candidates + 1))
    skip "$path" "partial reap after archive ${partial_archive_ref:-unknown}; operator review"
    return 0
  fi

  if [[ ! -d "$path" || ! -e "$path/.git" ]]; then
    skip "$path" "not a git directory"
    return 0
  fi

  real="$(realpath "$path")" || {
    echo "reap-lane: realpath failed: $path" >&2
    return 1
  }

  if [[ -n "$invalid_remote_agent_root_real" ]]; then
    case "$real" in
      "$invalid_remote_agent_root_real"/*)
        skip "$path" "WORKBAY_REMOTE_AGENT_ROOT must be strictly below HOME"
        return 0
        ;;
    esac
  fi

  case "$real" in
    "$home_real"/*) ;;
    *)
      skip "$path" "not under allowlisted lane root"
      return 0
      ;;
  esac
  if ! is_under_lane_root "$real"; then
    skip "$path" "not under allowlisted lane root"
    return 0
  fi
  if [[ -n "$archive_to_real" ]]; then
    case "$archive_to_real" in
      "$real"|"$real"/*)
        skip "$path" "archive destination is inside lane"
        return 0
        ;;
    esac
  fi

  if is_grok_sandbox "$real"; then
    # Materializers use this same lock. Take it before any destructive-run
    # eligibility read, then hold it through the final snapshot and removal so
    # a writer cannot make its work part of our trusted baseline.
    if [[ "$yes" -eq 1 ]] && ! acquire_grok_lane_lock "$real"; then
      freshness_candidates=$((freshness_candidates + 1))
      skip "$path" "${grok_lane_lock_error:-lane lock unverifiable: unknown error}"
      return 0
    fi
  fi

  # Resolve linked-worktree ownership independently of archive mode so every
  # successful removal can prune the parent's stale worktree metadata. For a
  # destructive sandbox run this and every later eligibility read are covered
  # by the materializer lock acquired above.
  parent="$(lane_parent_repo "$real" || true)"
  if [[ -z "$parent" ]] && has_linked_worktrees "$real"; then
    skip "$path" "repo has linked worktrees"
    return 0
  fi

  if is_grok_sandbox "$real"; then
    if ! grok_sandbox_is_stale "$real" "$path"; then
      return 0
    fi
  elif [[ -n "$archive_to" ]]; then
    min_age="${REAP_MIN_AGE_SEC:-3600}"
    case "$min_age" in
      ''|*[!0-9]*)
        skip "$path" "invalid minimum lane age"
        return 0
        ;;
    esac
    newest_mtime="$(lane_newest_mtime "$real" || true)"
    now="$(date +%s)"
    if [[ -z "$newest_mtime" ]]; then
      skip "$path" "could not determine lane age"
      return 0
    fi
    if [[ "$min_age" -gt 0 && $((now - newest_mtime)) -le "$min_age" ]]; then
      skip "$path" "lane is too recent"
      return 0
    fi
  fi
  freshness_candidates=$((freshness_candidates + 1))

  if [[ "$yes" -eq 1 ]] && lane_live_probe_blocks_reap "$real"; then
    skip "$path" "$live_probe_reason"
    return 0
  fi

  if [[ -n "$archive_to" ]]; then
    generation="$(archive_generation "$real" || true)"
    if [[ -z "$generation" ]]; then
      skip "$path" "could not determine archive generation"
      return 0
    fi
    ns="${real#"${home_real}"/}/${generation}"
    # Ordered cheapest-and-strictest first: neither an uncommitted tree nor a
    # stash has a commit behind it, so archiving cannot make them safe.
    if has_blocking_dirty "$real"; then
      skip_dirty "$path" "$real"
      return 0
    fi
    if stash_has_real_work "$real"; then
      skip "$path" "${git_guard_error:-stash has real work}"
      return 0
    fi
    if [[ "$yes" -eq 1 ]]; then
      if [[ -n "$parent" ]]; then
        safety_ignore_ref="refs/lanes/${ns}/HEAD"
      fi
      safety_snapshot="$(lane_safety_snapshot "$real" "$safety_ignore_ref")" || {
        release_grok_lane_lock
        skip "$path" "could not capture lane snapshot"
        return 0
      }
    fi
    if [[ -n "$parent" ]]; then
      if [[ "$yes" -eq 1 ]] && ! anchor_worktree_head "$real" "$ns" "$parent"; then
        release_grok_lane_lock
        skip "$path" "could not anchor HEAD in ${parent}"
        return 0
      fi
      archive_ref="refs/lanes/${ns}/HEAD"
      upstream_label="worktree-of:${parent}"
    else
      upstream_label="archived:${archive_to}"
      if [[ "$yes" -eq 1 ]] && ! archive_lane "$real" "$ns"; then
        release_grok_lane_lock
        if [[ "$archive_error" == ref\ enumeration\ failed:* ]]; then
          skip "$path" "$archive_error"
        elif ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
          skip "$path" "lane changed after snapshot; skipped"
        else
          skip "$path" "${archive_error:-archive failed: no diagnostic}"
        fi
        return 0
      fi
      archive_ref="${archive_head_ref:-refs/lanes/${ns}/HEAD}"
    fi
    if [[ "$yes" -eq 1 ]] && ! archive_reflog_only_commits "$real" "$ns"; then
      release_grok_lane_lock
      if ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
        skip "$path" "lane changed after snapshot; skipped"
      else
        skip "$path" "${archive_error:-archive reflog failed: no diagnostic}"
      fi
      return 0
    fi
  elif [[ -n "${REAP_UPSTREAM:-}" ]]; then
    if [[ "$REAP_UPSTREAM" != *#* ]]; then
      skip "$path" "REAP_UPSTREAM must be <url>#<ref>"
      return 0
    fi
    ref="${REAP_UPSTREAM##*#}"
    url="${REAP_UPSTREAM%#*}"
    if git_net -C "$real" fetch --quiet -- "$url" "$ref" >/dev/null 2>&1; then
      :
    else
      net_status=$?
      if git_net_timed_out "$net_status"; then skip "$path" "fetch timed out"
      else skip "$path" "fetch failed"; fi
      return 0
    fi
    upstream_label="$REAP_UPSTREAM"
  else
    if ! git -C "$real" remote get-url origin >/dev/null 2>&1; then
      skip "$path" "no origin remote and REAP_UPSTREAM unset"
      return 0
    fi
    if git_net -C "$real" fetch --quiet origin main >/dev/null 2>&1; then
      :
    else
      net_status=$?
      if git_net_timed_out "$net_status"; then skip "$path" "fetch timed out"
      else skip "$path" "fetch failed"; fi
      return 0
    fi
    upstream_label="origin/main"
  fi

  if [[ -z "$archive_to" ]]; then
    upstream="$(git -C "$real" rev-parse --verify FETCH_HEAD)"

    if has_unmerged_work "$real" "$upstream"; then
      skip "$path" "unmerged local work"
      return 0
    fi

    if has_blocking_dirty "$real"; then
      skip_dirty "$path" "$real"
      return 0
    fi

    if stash_has_real_work "$real"; then
      skip "$path" "${git_guard_error:-stash has real work}"
      return 0
    fi
    if [[ "$yes" -eq 1 ]]; then
      safety_snapshot="$(lane_safety_snapshot "$real")" || {
        release_grok_lane_lock
        skip "$path" "could not capture lane snapshot"
        return 0
      }
    fi
  fi

  size="$(du -sh "$real" | awk '{print $1}')"
  size_kib="$(du -sk "$real" | awk '{print $1}')"
  head_sha="$(git -C "$real" rev-parse HEAD)"

  if [[ "$yes" -eq 0 ]]; then
    printf 'WOULD REAP %s (%s)\n' "$real" "$size"
    note_lock_only_reap "$real"
    return 0
  fi

  # This is the final complete state check. Sandboxes also have a materializer
  # lock, while ordinary archive roots rely on the process/ownership probe below
  # because they have no shared worker lease. Keep both checks immediately next
  # to deletion so a worker entering during archive preparation is observed.
  if ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
    release_grok_lane_lock
    skip "$path" "lane changed after snapshot; skipped"
    return 0
  fi

  if ! grok_lane_lock_matches "$real"; then
    release_grok_lane_lock
    skip "$path" "${grok_lane_lock_error:-lane lock unverifiable: unknown error}"
    return 0
  fi

  partial_intent_path=""
  if [[ -n "$archive_ref" ]]; then
    if ! write_partial_intent "$real" "$archive_ref" "$head_sha"; then
      release_grok_lane_lock
      skip "$path" "could not record partial-reap intent; lane retained"
      return 1
    fi
    partial_intent_path="$(partial_intent_path_for "$real")"
  fi

  # Archive roots do not have the sandbox materializer's lease. A final /proc
  # scan next to rm is not atomic: a worker can enter after the scan and lose
  # its live worktree. Rename the checkout out of the worker entry path, then
  # re-probe the quarantine inode, then delete that aside copy. Remove a newly
  # written partial intent before a live-process refusal so it stays a retry,
  # not a misleading operator-review tombstone.
  if lane_live_probe_blocks_reap "$real"; then
    [[ -n "$partial_intent_path" ]] && rm -f -- "$partial_intent_path"
    skip "$path" "$live_probe_reason"
    return 0
  fi

  quarantine="$(quarantine_lane "$real")" || {
    [[ -n "$partial_intent_path" ]] && rm -f -- "$partial_intent_path"
    skip "$path" "could not quarantine lane for deletion"
    return 1
  }

  if lane_live_probe_blocks_reap "$quarantine"; then
    [[ -n "$partial_intent_path" ]] && rm -f -- "$partial_intent_path"
    if restore_quarantined_lane "$real" "$quarantine"; then
      skip "$path" "$live_probe_reason"
      return 0
    fi
    skip "$path" "$live_probe_reason; could not restore quarantine at $quarantine: ${restore_quarantined_error:-unknown restore failure}"
    return 1
  fi

  if ! rm -rf -- "$quarantine" || [[ -e "$quarantine" ]]; then
    if ! restore_quarantined_lane "$real" "$quarantine"; then
      restore_error="${restore_quarantined_error:-unknown restore failure}"
    fi
    if [[ -n "$archive_ref" ]]; then
      if [[ -n "$restore_error" ]]; then
        skip "$path" "rm failed after archive ${archive_ref}; lane partially removed; could not restore quarantine at $quarantine: $restore_error"
      else
        skip "$path" "rm failed after archive ${archive_ref}; lane partially removed"
      fi
    else
      if [[ -n "$restore_error" ]]; then
        skip "$path" "rm failed; lane partially removed; could not restore quarantine at $quarantine: $restore_error"
      else
        skip "$path" "rm failed; lane partially removed"
      fi
    fi
    return 1
  fi
  reaped=$((reaped + 1))
  note_lock_only_reap "$real"
  bytes_freed=$((bytes_freed + size_kib * 1024))
  if ! grok_lane_lock_matches "$real"; then
    echo "reap-lane: warning: ${grok_lane_lock_error:-lane lock unverifiable} after removal; sibling cleanup skipped for $real" >&2
  else
    if ! cleanup_grok_sandbox_siblings "$real"; then
      echo "reap-lane: could not remove sandbox siblings for $real" >&2
      cleanup_failed=1
    fi
  fi
  # Stale worktree metadata makes the parent's `worktree list` lie, and leaves
  # the per-worktree HEAD holding a commit we have already anchored properly.
  if [[ -n "${parent:-}" ]]; then
    git -C "$parent" worktree prune >/dev/null 2>&1 || true
  fi
  log_dir="$(dirname "$log")"
  mkdir -p "$log_dir"
  printf '%s %s %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$real" "$size" "$head_sha" "$upstream_label" >>"$log"
  if [[ -n "$partial_intent_path" ]]; then
    rm -f "$partial_intent_path"
  fi
  release_grok_lane_lock
  [[ "$cleanup_failed" -eq 0 ]] || return 1
  return 0
}

rc="$all_roots_missing"
for path in ${paths[@]+"${paths[@]}"}; do
  if ! process_one "$path"; then
    rc=1
  fi
done

df_used_pct="$(df -P "$HOME" 2>/dev/null | awk 'NR == 2 { sub(/%$/, "", $5); print $5; exit }')" || df_used_pct=""
case "$df_used_pct" in
  ''|*[!0-9]*)
    echo "reap-lane: could not determine filesystem usage; assuming 100%" >&2
    df_used_pct=100
    ;;
esac
print_triage
printf 'REAP SUMMARY candidates=%s reaped=%s skipped=%s bytes_freed=%s df_used_pct=%s\n' \
  "$candidates" "$reaped" "$skipped" "$bytes_freed" "$df_used_pct"

if [[ "$rc" -eq 0 && "$yes" -eq 1 && "${#all_roots[@]}" -gt 0 &&
      "$freshness_candidates" -gt 0 && "$reaped" -eq 0 &&
      "$df_used_pct" -ge "${REAP_DF_ALERT_PCT:-85}" ]]; then
  exit 4
fi
exit "$rc"
