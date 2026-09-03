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

for all_root in ${all_roots[@]+"${all_roots[@]}"}; do
  if [[ ! -d "$all_root" ]]; then
    echo "reap-lane: --all root is not a directory: $all_root" >&2
    exit 1
  fi
  shopt -s nullglob
  for cand in "$all_root"/*; do
    if [[ -d "$cand" ]]; then
      paths+=("$cand")
    fi
  done
  shopt -u nullglob
done

home_real="$(realpath "$HOME")"

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

candidates=0
freshness_candidates=0
reaped=0
skipped=0
bytes_freed=0
grok_lane_lock_held=0
grok_lane_lock_path=""
grok_marker_backfill=0

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

path_mtime() {
  local mtime
  mtime="$(stat -c %Y "$1" 2>/dev/null)" || mtime="$(stat -f %m "$1" 2>/dev/null)" || return 1
  case "$mtime" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$mtime"
}

is_grok_sandbox() {
  case "$1" in
    "$home_real/grok-sandbox/"*) return 0 ;;
  esac
  return 1
}

# Apply the same marker/lease/TTL contract as scripts/remote_agent.sh. Returns
# success only after the sandbox is old and unoccupied; deletion still takes
# the per-lane lock immediately before archive/anchor and holds it through rm.
grok_sandbox_is_stale() {
  local real="$1" path="$2" root key marker lease ttl now mtime issued expiry lease_line
  grok_marker_backfill=0
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
    mtime="$(path_mtime "$real" || true)"
    now="$(date +%s)"
    if [[ -z "$mtime" || $((now - mtime)) -le "$ttl" ]]; then
      skip "$path" "sandbox marker missing"
      return 1
    fi
    # Remember legacy eligibility without mutating the checkout. The marker is
    # committed only after every guard/archive succeeds and immediately before
    # deletion, while the lane lock is held when one exists.
    grok_marker_backfill=1
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

backfill_grok_sandbox_marker() {
  local real="$1" root key marker marker_tmp
  [[ "$grok_marker_backfill" -eq 1 ]] || return 0
  root="$(dirname "$real")"
  key="${real##*/}"
  marker="$real/.workbay-lane-sandbox"
  marker_tmp="$root/.reap-marker-$key-$$"
  if ! printf 'lane_key=%s\n' "$key" >"$marker_tmp" ||
     ! touch -r "$real" "$marker_tmp"; then
    rm -f "$marker_tmp" >/dev/null 2>&1 || true
    return 1
  fi
  if ! grep -qxF '.workbay-lane-sandbox' "$real/.git/info/exclude" 2>/dev/null &&
     ! printf '%s\n' .workbay-lane-sandbox >>"$real/.git/info/exclude"; then
    rm -f "$marker_tmp" >/dev/null 2>&1 || true
    return 1
  fi
  if ! mv "$marker_tmp" "$marker"; then
    rm -f "$marker_tmp" >/dev/null 2>&1 || true
    return 1
  fi
  grok_marker_backfill=0
  return 0
}

acquire_grok_lane_lock() {
  local real="$1" root key lane_lock
  is_grok_sandbox "$real" || return 0
  root="$(dirname "$real")"
  key="${real##*/}"
  lane_lock="$root/.lane-lock-$key"
  if ! command -v flock >/dev/null 2>&1; then
    return 1
  fi
  # Create-or-open the stable materializer lock path, then lock and verify the
  # inode. Treating absence as unlocked leaves no fd against which to detect a
  # path materialized during the final deletion window.
  exec 8>>"$lane_lock"
  if ! flock -n 8 || [[ ! "$lane_lock" -ef /dev/fd/8 ]]; then
    exec 8>&-
    return 1
  fi
  grok_lane_lock_held=1
  grok_lane_lock_path="$lane_lock"
  return 0
}

grok_lane_lock_matches() {
  local real="$1"
  is_grok_sandbox "$real" || return 0
  [[ "$grok_lane_lock_held" -eq 1 && -n "$grok_lane_lock_path" &&
     -e "$grok_lane_lock_path" && "$grok_lane_lock_path" -ef /dev/fd/8 ]]
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
  [[ "$rel" == */* ]] || return 1
  first="${rel%%/*}"
  for root in $REAP_LANE_ROOTS; do
    [[ "$first" == "$root" ]] && return 0
  done
  return 1
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
  local dir="$1" line entry left right
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    entry="${line:3}"
    if [[ "$entry" == *" -> "* ]]; then
      left="${entry%% -> *}"
      right="${entry#* -> }"
      if ! is_ignorable_path "$left" || ! is_ignorable_path "$right"; then
        return 0
      fi
    elif ! is_ignorable_path "$entry"; then
      return 0
    fi
  done < <(git -C "$dir" status --porcelain)
  return 1
}

stash_has_real_work() {
  local dir="$1" sha f
  git -C "$dir" rev-parse --verify --quiet refs/stash >/dev/null || return 1
  while IFS= read -r sha; do
    [[ -z "$sha" ]] && continue
    if ! git -C "$dir" diff --quiet "${sha}^1" "$sha"; then
      return 0
    fi
    if git -C "$dir" rev-parse --verify --quiet "${sha}^3" >/dev/null; then
      while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        if ! is_ignorable_path "$f"; then
          return 0
        fi
      done < <(git -C "$dir" ls-tree -r --name-only "${sha}^3")
    fi
  done < <(git -C "$dir" stash list --format='%H')
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
# Not --force: these refs may be the only copy of that lane's history, so a
# diverged re-archive must be refused rather than overwritten.
archive_lane() {
  local dir="$1" ns="$2" head_sha want got ref sha source_ref
  local ref_specs=()
  if ! git -C "$dir" rev-parse --verify --quiet HEAD >/dev/null; then
    return 1
  fi
  if [[ -n "$(git -C "$dir" for-each-ref --format='%(objectname)' refs/heads)" ]]; then
    git -C "$dir" push --quiet --no-verify -- "$archive_to" \
      "refs/heads/*:refs/lanes/${ns}/*" >/dev/null 2>&1 || return 1
  fi
  # Keep the historical branch namespace for consumers, plus an unambiguous
  # refs/ mirror that retains tags, notes, replacement refs, and any other
  # local ref without flattening unlike kinds onto one destination.
  while IFS= read -r source_ref; do
    [[ -z "$source_ref" ]] && continue
    ref_specs+=("${source_ref}:refs/lanes/${ns}/refs/${source_ref#refs/}")
  done < <(git -C "$dir" for-each-ref --format='%(refname)' refs)
  if [[ ${#ref_specs[@]} -gt 0 ]]; then
    git -C "$dir" push --quiet --no-verify -- "$archive_to" \
      "${ref_specs[@]}" >/dev/null 2>&1 || return 1
  fi
  head_sha="$(git -C "$dir" rev-parse HEAD)"
  # Named explicitly: commits reachable only from a detached HEAD are the
  # easiest work to lose and the hardest to notice missing.
  git -C "$dir" push --quiet --no-verify -- "$archive_to" \
    "${head_sha}:refs/lanes/${ns}/HEAD" >/dev/null 2>&1 || return 1

  # Read the refs back out of the archive. A push that reported success but
  # landed nothing would otherwise be indistinguishable from one that worked,
  # and the next step is rm -rf.
  want="$(
    git -C "$dir" for-each-ref --format="refs/lanes/${ns}/%(refname:strip=2) %(objectname)" refs/heads
    git -C "$dir" for-each-ref --format="refs/lanes/${ns}/refs/%(refname:strip=1) %(objectname)" refs
    printf 'refs/lanes/%s/HEAD %s\n' "$ns" "$head_sha"
  )"
  got="$(git ls-remote -- "$archive_to" "refs/lanes/${ns}/*" 2>/dev/null |
    awk '{ print $2, $1 }')" || return 1
  while IFS=' ' read -r ref sha; do
    [[ -z "$ref" ]] && continue
    printf '%s\n' "$got" | grep -qxF "$ref $sha" || return 1
  done <<<"$want"
  return 0
}

# Preserve commits named by a reflog but unreachable from every current ref.
# The lane owns those reflogs; rm would otherwise remove their only names.
archive_reflog_only_commits() {
  local dir="$1" ns="$2" reachable reflog_output got sha ref
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
  git -C "$dir" push --quiet --no-verify -- "$archive_to" \
    "${ref_specs[@]}" >/dev/null 2>&1 || return 1
  got="$(git ls-remote -- "$archive_to" "refs/reaped/${ns}/reflog/*" 2>/dev/null |
    awk '{ print $2, $1 }')" || return 1
  for sha in "${reflog_shas[@]}"; do
    ref="refs/reaped/${ns}/reflog/${sha}"
    printf '%s\n' "$got" | grep -qxF "$ref $sha" || return 1
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
  local safety_snapshot safety_ignore_ref=""

  candidates=$((candidates + 1))

  if [[ ! -d "$path" || ! -e "$path/.git" ]]; then
    skip "$path" "not a git directory"
    return 0
  fi

  real="$(realpath "$path")" || {
    echo "reap-lane: realpath failed: $path" >&2
    return 1
  }

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
      skip "$path" "sandbox lane lock is held or cannot be verified"
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
      skip "$path" "dirty working tree"
      return 0
    fi
    if stash_has_real_work "$real"; then
      skip "$path" "stash has real work"
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
      upstream_label="worktree-of:${parent}"
    else
      upstream_label="archived:${archive_to}"
      if [[ "$yes" -eq 1 ]] && ! archive_lane "$real" "$ns"; then
        release_grok_lane_lock
        if ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
          skip "$path" "lane changed after snapshot; skipped"
        else
          skip "$path" "could not archive to ${archive_to}"
        fi
        return 0
      fi
    fi
    if [[ "$yes" -eq 1 ]] && ! archive_reflog_only_commits "$real" "$ns"; then
      release_grok_lane_lock
      if ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
        skip "$path" "lane changed after snapshot; skipped"
      else
        skip "$path" "could not archive reflog to ${archive_to}"
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
    if ! git -C "$real" fetch --quiet -- "$url" "$ref" >/dev/null 2>&1; then
      skip "$path" "fetch failed"
      return 0
    fi
    upstream_label="$REAP_UPSTREAM"
  else
    if ! git -C "$real" remote get-url origin >/dev/null 2>&1; then
      skip "$path" "no origin remote and REAP_UPSTREAM unset"
      return 0
    fi
    if ! git -C "$real" fetch --quiet origin main >/dev/null 2>&1; then
      skip "$path" "fetch failed"
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
      skip "$path" "dirty working tree"
      return 0
    fi

    if stash_has_real_work "$real"; then
      skip "$path" "stash has real work"
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
    if [[ "$grok_marker_backfill" -eq 1 ]]; then
      printf 'WOULD REAP %s (legacy, marker backfill)\n' "$real"
    else
      printf 'WOULD REAP %s (%s)\n' "$real" "$size"
    fi
    return 0
  fi

  # This is the final complete state check. There remains an unavoidable race
  # between this comparison and rm below (plus marker backfill for a legacy
  # sandbox); callers that can mutate sandboxes must use the per-lane lock.
  if ! lane_matches_snapshot "$real" "$safety_ignore_ref" "$safety_snapshot"; then
    release_grok_lane_lock
    skip "$path" "lane changed after snapshot; skipped"
    return 0
  fi

  if ! grok_lane_lock_matches "$real"; then
    release_grok_lane_lock
    skip "$path" "lane lock replaced; skipped"
    return 0
  fi

  if is_grok_sandbox "$real" && ! backfill_grok_sandbox_marker "$real"; then
    release_grok_lane_lock
    skip "$path" "could not backfill sandbox marker"
    return 0
  fi
  # Marker backfill is filesystem work, so re-check once more immediately
  # before rm rather than extending trust from the preceding inode check.
  if ! grok_lane_lock_matches "$real"; then
    release_grok_lane_lock
    skip "$path" "lane lock replaced; skipped"
    return 0
  fi

  if ! rm -rf -- "$real" || [[ -e "$real" ]]; then
    release_grok_lane_lock
    skip "$path" "rm failed"
    return 1
  fi
  reaped=$((reaped + 1))
  bytes_freed=$((bytes_freed + size_kib * 1024))
  if ! grok_lane_lock_matches "$real"; then
    skip "$path" "lane lock replaced; skipped"
    release_grok_lane_lock
    return 0
  fi
  if ! cleanup_grok_sandbox_siblings "$real"; then
    echo "reap-lane: could not remove sandbox siblings for $real" >&2
    cleanup_failed=1
  fi
  # Stale worktree metadata makes the parent's `worktree list` lie, and leaves
  # the per-worktree HEAD holding a commit we have already anchored properly.
  if [[ -n "${parent:-}" ]]; then
    git -C "$parent" worktree prune >/dev/null 2>&1 || true
  fi
  log_dir="$(dirname "$log")"
  mkdir -p "$log_dir"
  printf '%s %s %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$real" "$size" "$head_sha" "$upstream_label" >>"$log"
  release_grok_lane_lock
  [[ "$cleanup_failed" -eq 0 ]] || return 1
  return 0
}

rc=0
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
printf 'REAP SUMMARY candidates=%s reaped=%s skipped=%s bytes_freed=%s df_used_pct=%s\n' \
  "$candidates" "$reaped" "$skipped" "$bytes_freed" "$df_used_pct"

if [[ "$rc" -eq 0 && "$yes" -eq 1 && "${#all_roots[@]}" -gt 0 &&
      "$freshness_candidates" -gt 0 && "$reaped" -eq 0 &&
      "$df_used_pct" -ge "${REAP_DF_ALERT_PCT:-85}" ]]; then
  exit 4
fi
exit "$rc"
