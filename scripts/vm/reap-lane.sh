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
  exit 2
}

: "${HOME:?HOME must be set}"

yes=0
log="${HOME}/reap-lane.log"
all_roots=()
archive_to=""
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

if [[ ${#all_roots[@]} -eq 0 && ${#paths[@]} -eq 0 ]]; then
  usage
fi

home_real="$(realpath "$HOME")"

# Every directory under $HOME that accumulates lane clones. [RES-07] a reclaimer
# whose scope does not match what grows is not a reclaimer: this list read
# `w3 uxw2 l1` (1.6G on the VM) while ~/w held 18G and ~/lanes 9.2G, and the
# disk reached 96% with the weekly cron reporting success throughout.
# Space-separated and overridable so a new lane root is a cron edit, not a code
# change. An override REPLACES the defaults -- narrowing the roots for a one-off
# sweep must not silently still reap the standing ones.
REAP_LANE_ROOTS="${REAP_LANE_ROOTS:-w3 uxw2 l1 w lanes}"

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
  printf 'SKIP %s: %s\n' "$1" "$2"
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
  local dir="$1" upstream="$2" rev head_rev
  while IFS= read -r rev; do
    [[ -z "$rev" ]] && continue
    if ! git -C "$dir" merge-base --is-ancestor "$rev" "$upstream"; then
      return 0
    fi
  done < <(git -C "$dir" for-each-ref --format='%(objectname)' refs/heads)
  head_rev="$(git -C "$dir" rev-parse HEAD)"
  if ! git -C "$dir" merge-base --is-ancestor "$head_rev" "$upstream"; then
    return 0
  fi
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
  local dir="$1" ns="$2" head_sha want got ref sha
  if ! git -C "$dir" rev-parse --verify --quiet HEAD >/dev/null; then
    return 1
  fi
  if [[ -n "$(git -C "$dir" for-each-ref --format='%(objectname)' refs/heads)" ]]; then
    git -C "$dir" push --quiet --no-verify -- "$archive_to" \
      "refs/heads/*:refs/lanes/${ns}/*" >/dev/null 2>&1 || return 1
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

# Return 0 = skip or reaped (normal); 1 = internal error.
process_one() {
  local path="$1"
  local real size head_sha upstream upstream_label url ref log_dir

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

  if [[ -n "$archive_to" ]]; then
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
    if ! archive_lane "$real" "${real#"${home_real}"/}"; then
      skip "$path" "could not archive to ${archive_to}"
      return 0
    fi
    upstream_label="archived:${archive_to}"
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
  fi

  size="$(du -sh "$real" | awk '{print $1}')"
  head_sha="$(git -C "$real" rev-parse HEAD)"

  if [[ "$yes" -eq 0 ]]; then
    printf 'WOULD REAP %s (%s)\n' "$real" "$size"
    return 0
  fi

  rm -rf -- "$real"
  log_dir="$(dirname "$log")"
  mkdir -p "$log_dir"
  printf '%s %s %s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$real" "$size" "$head_sha" "$upstream_label" >>"$log"
  return 0
}

rc=0
for path in "${paths[@]}"; do
  if ! process_one "$path"; then
    rc=1
  fi
done
exit "$rc"
