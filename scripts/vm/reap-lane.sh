#!/usr/bin/env bash
# Guarded lane-clone reaper. Default is dry-run; --yes actually rm -rf.
# Usage:
#   reap-lane.sh [--yes] [--log FILE] PATH...
#   reap-lane.sh [--yes] [--log FILE] --all ROOT
set -euo pipefail

export GIT_TERMINAL_PROMPT=0

usage() {
  echo "Usage: reap-lane.sh [--yes] [--log FILE] PATH..." >&2
  echo "       reap-lane.sh [--yes] [--log FILE] --all ROOT" >&2
  exit 2
}

: "${HOME:?HOME must be set}"

yes=0
log="${HOME}/reap-lane.log"
all_root=""
paths=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes) yes=1; shift ;;
    --log)
      [[ $# -ge 2 ]] || usage
      log="$2"
      shift 2
      ;;
    --all)
      [[ $# -ge 2 ]] || usage
      all_root="$2"
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

if [[ -n "$all_root" ]]; then
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
fi

if [[ -z "$all_root" && ${#paths[@]} -eq 0 ]]; then
  usage
fi

home_real="$(realpath "$HOME")"

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
  case "$real" in
    */w3/*|*/uxw2/*|*/l1/*) ;;
    *)
      skip "$path" "not under allowlisted lane root"
      return 0
      ;;
  esac

  if [[ -n "${REAP_UPSTREAM:-}" ]]; then
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
