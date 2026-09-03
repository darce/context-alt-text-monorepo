#!/usr/bin/env bash
# Pure-local tests for reap-lane.sh (no network). Exit non-zero on any failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT}/scripts/vm/reap-lane.sh"

failures=0
skips=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }
skip_case() { echo "SKIP: $* (flock unavailable)"; skips=$((skips + 1)); }

if [[ ! -f "$SCRIPT" ]]; then
  echo "FAIL: missing $SCRIPT"
  exit 1
fi

# `pwd -P` resolves symlinks: on macOS TMPDIR is /var/folders/... and /var is a
# symlink to /private/var. reap-lane.sh reports the realpath, so without this the
# suite fails on a laptop for a reason that has nothing to do with the reaper.
WORKDIR="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/reap-lane-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$WORKDIR"' EXIT
export HOME="$WORKDIR"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_TERMINAL_PROMPT=0
export GIT_ALLOW_PROTOCOL=file
mkdir -p "$HOME/w3" "$HOME/uxw2" "$HOME/l1" "$HOME/w" "$HOME/lanes"

ORIGIN="$WORKDIR/origin.git"

git_ident() {
  git -C "$1" config user.email "reaper@test"
  git -C "$1" config user.name "reaper"
  git -C "$1" config commit.gpgsign false
}

init_origin() {
  local seed="$WORKDIR/seed"
  mkdir -p "$seed"
  git init -b main "$seed" >/dev/null
  git_ident "$seed"
  echo "seed" >"$seed/README"
  git -C "$seed" add README
  git -C "$seed" commit -q -m "init"
  git clone --bare --quiet "$seed" "$ORIGIN"
}

clone_lane() {
  local dest="$1"
  mkdir -p "$(dirname "$dest")"
  git clone --quiet "file://${ORIGIN}" "$dest"
  git_ident "$dest"
}

mark_sandbox() {
  local lane="$1"
  printf '%s\n' .workbay-lane-sandbox >>"$lane/.git/info/exclude"
  printf 'lane_key=%s\n' "${lane##*/}" >"$lane/.workbay-lane-sandbox"
}

run_reap() {
  set +e
  out="$(bash "$SCRIPT" "$@" 2>&1)"
  rc=$?
  set -e
}

assert_rc0() {
  local label="$1"
  if [[ "$rc" -eq 0 ]]; then
    pass "$label exit 0"
  else
    fail "$label expected exit 0 got $rc; out=$out"
  fi
}

assert_contains() {
  local label="$1" needle="$2"
  if [[ "$out" == *"$needle"* ]]; then
    pass "$label contains ${needle}"
  else
    fail "$label missing '${needle}'; out=$out"
  fi
}

assert_not_contains() {
  local label="$1" needle="$2"
  if [[ "$out" != *"$needle"* ]]; then
    pass "$label omits ${needle}"
  else
    fail "$label unexpectedly contains '${needle}'; out=$out"
  fi
}

assert_exists() {
  local label="$1" path="$2"
  if [[ -d "$path" ]]; then
    pass "$label still exists"
  else
    fail "$label should still exist: $path"
  fi
}

assert_path_exists() {
  local label="$1" path="$2"
  if [[ -e "$path" ]]; then
    pass "$label still exists"
  else
    fail "$label should still exist: $path"
  fi
}

assert_gone() {
  local label="$1" path="$2"
  if [[ ! -e "$path" ]]; then
    pass "$label deleted"
  else
    fail "$label should be deleted: $path (out=$out)"
  fi
}

assert_summary() {
  local label="$1" candidates="$2" reaped="$3" skipped="$4" bytes="$5"
  local pattern="^REAP SUMMARY candidates=${candidates} reaped=${reaped} skipped=${skipped} bytes_freed=${bytes} df_used_pct=[0-9]+$"
  if grep -Eq "$pattern" <<<"$out"; then
    pass "$label summary"
  else
    fail "$label missing summary matching '$pattern'; out=$out"
  fi
}

assert_summary_counts() {
  local label="$1" candidates="$2" reaped="$3" skipped="$4"
  local pattern="^REAP SUMMARY candidates=${candidates} reaped=${reaped} skipped=${skipped} bytes_freed=[0-9]+ df_used_pct=[0-9]+$"
  if grep -Eq "$pattern" <<<"$out"; then
    pass "$label summary counts"
  else
    fail "$label missing summary matching '$pattern'; out=$out"
  fi
}

# Bash 3.2 has no timed `wait`. Background race fixtures write an exit marker
# from an EXIT trap; poll that marker for at most ten seconds, then kill and
# reap the child so a broken synchronization hook cannot stall the suite.
wait_for_background_pid() {  # $1 pid, $2 exit marker, $3 label
  local pid="$1" exit_marker="$2" label="$3" attempt=0 child_rc
  while [[ ! -e "$exit_marker" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  if [[ ! -e "$exit_marker" ]]; then
    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true
    fail "$label timed out waiting for background writer"
    return 1
  fi
  set +e
  wait "$pid"
  child_rc=$?
  set -e
  if [[ "$child_rc" -ne 0 ]]; then
    fail "$label background writer exited $child_rc"
    return 1
  fi
  return 0
}

init_origin

# A second reaper must fail closed before inspecting any lane. Hold the same
# whole-sweep lock with the platform's locking primitive and prove the checkout
# is not even reported as a candidate.
lane_lock="$HOME/w3/lane-lock"
clone_lane "$lane_lock"
lock_path="$HOME/.reap-lane.lock"
lock_ready="$WORKDIR/lock-ready"
lock_release="$WORKDIR/lock-release"
if command -v flock >/dev/null 2>&1; then
  (
    exec 8>"$lock_path"
    flock 8
    : >"$lock_ready"
    while [[ ! -e "$lock_release" ]]; do sleep 0.05; done
  ) &
else
  (
    mkdir "${lock_path}.d"
    : >"$lock_ready"
    while [[ ! -e "$lock_release" ]]; do sleep 0.05; done
    rmdir "${lock_path}.d"
  ) &
fi
lock_holder_pid=$!
for _ in {1..100}; do
  [[ -e "$lock_ready" ]] && break
  sleep 0.05
done
if [[ -e "$lock_ready" ]]; then
  run_reap "$lane_lock"
  if [[ "$rc" -eq 3 ]]; then pass "concurrent reaper exit 3"
  else fail "concurrent reaper expected exit 3 got $rc; out=$out"; fi
  if [[ "$out" != *"WOULD REAP"* ]]; then pass "concurrent reaper did not inspect lane"
  else fail "concurrent reaper inspected lane; out=$out"; fi
  assert_exists "concurrent reaper" "$lane_lock"
else
  fail "concurrent reaper lock holder did not start"
fi
: >"$lock_release"
wait "$lock_holder_pid"

# Exercise the macOS-compatible mkdir fallback even on hosts that provide
# flock. Only the commands reached before the expected lock refusal are made
# available, so command -v flock must fail inside reap-lane.sh.
mkdir_lock_bin="$WORKDIR/mkdir-lock-bin"
mkdir -p "$mkdir_lock_bin"
for command_name in bash mkdir mv ps realpath rm rmdir; do
  ln -s "$(command -v "$command_name")" "$mkdir_lock_bin/$command_name"
done
mkdir "${lock_path}.d"
PATH="$mkdir_lock_bin" run_reap "$lane_lock"
if [[ "$rc" -eq 3 ]]; then pass "mkdir fallback concurrent reaper exit 3"
else fail "mkdir fallback concurrent reaper expected exit 3 got $rc; out=$out"; fi
assert_contains "mkdir fallback concurrent reaper" "another reaper holds $lock_path"
rmdir "${lock_path}.d"

# A mkdir lock left behind by an untrappable death must not disable every
# future sweep. Ownership metadata lets the fallback recover only a lock whose
# recorded process is definitely gone; missing/malformed metadata stays held.
mkdir "${lock_path}.d"
printf 'pid=99999999\n' >"${lock_path}.d/owner"
PATH="$mkdir_lock_bin" run_reap --all "$WORKDIR/missing-root"
if [[ "$rc" -eq 1 ]]; then pass "mkdir fallback stale lock recovered"
else fail "mkdir fallback stale lock expected post-lock exit 1 got $rc; out=$out"; fi
if [[ ! -e "${lock_path}.d" ]]; then pass "mkdir fallback stale lock released"
else fail "mkdir fallback stale lock directory survived"; fi
stale_owner_copy="$(find "$HOME" -type f -path "${lock_path}.d.stale.*/owner" -print -quit 2>/dev/null || true)"
if [[ -n "$stale_owner_copy" ]] && grep -qxF 'pid=99999999' "$stale_owner_copy"; then
  pass "mkdir fallback atomically preserved stale owner"
else
  fail "mkdir fallback removed an owner file it did not write"
fi

# Two stale-lock recoverers may agree the old PID is dead, but only the one
# that atomically renames that lock directory may enter the sweep.
race_lock_bin="$WORKDIR/race-lock-bin"
mkdir "$race_lock_bin"
for command_name in awk bash date dirname du git grep mkdir mv ps rm rmdir sleep stat; do
  ln -s "$(command -v "$command_name")" "$race_lock_bin/$command_name"
done
real_realpath="$(command -v realpath)"
cat >"$race_lock_bin/realpath" <<'RACE_REALPATH'
#!/usr/bin/env bash
sleep 1
exec "$REAL_REALPATH" "$@"
RACE_REALPATH
chmod +x "$race_lock_bin/realpath"
mkdir "${lock_path}.d"
printf 'pid=99999999\n' >"${lock_path}.d/owner"
PATH="$race_lock_bin" REAL_REALPATH="$real_realpath" \
  bash "$SCRIPT" "$lane_lock" >"$WORKDIR/race-one.out" 2>&1 &
race_one_pid=$!
PATH="$race_lock_bin" REAL_REALPATH="$real_realpath" \
  bash "$SCRIPT" "$lane_lock" >"$WORKDIR/race-two.out" 2>&1 &
race_two_pid=$!
set +e
wait "$race_one_pid"; race_one_rc=$?
wait "$race_two_pid"; race_two_rc=$?
set -e
if [[ "$race_one_rc:$race_two_rc" == "0:3" || "$race_one_rc:$race_two_rc" == "3:0" ]]; then
  pass "mkdir fallback stale recovery admits exactly one reaper"
else
  fail "mkdir fallback stale recovery statuses $race_one_rc/$race_two_rc; one=$(cat "$WORKDIR/race-one.out"); two=$(cat "$WORKDIR/race-two.out")"
fi

# ---------------------------------------------------------------------------
# (a) merged clean clone -> WOULD REAP (dry-run) and is deleted with --yes.
# Isolates: all guards pass; dry-run does not delete.
# ---------------------------------------------------------------------------
lane_a="$HOME/w3/lane-a"
clone_lane "$lane_a"
run_reap "$lane_a"
assert_rc0 "a dry-run"
assert_contains "a dry-run" "WOULD REAP"
assert_contains "a dry-run" "$lane_a"
assert_exists "a dry-run" "$lane_a"

run_reap --yes --log "$HOME/reap-lane.log" "$lane_a"
assert_rc0 "a --yes"
assert_gone "a --yes" "$lane_a"
if [[ -f "$HOME/reap-lane.log" ]] && grep -q "$lane_a" "$HOME/reap-lane.log"; then
  pass "a --yes logged path"
else
  fail "a --yes missing log line for $lane_a; log=$(cat "$HOME/reap-lane.log" 2>/dev/null || true)"
fi

# ---------------------------------------------------------------------------
# (b) clone with unmerged local branch -> SKIP, still exists after --yes.
# Isolates guard 4 (ancestor / unmerged work).
# ---------------------------------------------------------------------------
lane_b="$HOME/w3/lane-b"
clone_lane "$lane_b"
git -C "$lane_b" checkout -q -b unmerged
echo extra >"$lane_b/extra.txt"
git -C "$lane_b" add extra.txt
git -C "$lane_b" commit -q -m "unmerged"
git -C "$lane_b" checkout -q main
run_reap --yes "$lane_b"
assert_rc0 "b unmerged"
assert_contains "b unmerged" "SKIP"
assert_contains "b unmerged" "unmerged local work"
assert_exists "b unmerged --yes" "$lane_b"

# ---------------------------------------------------------------------------
# (c) clone with dirty tracked file -> SKIP.
# Isolates guard 5 (dirty working tree).
# ---------------------------------------------------------------------------
lane_c="$HOME/w3/lane-c"
clone_lane "$lane_c"
echo dirty >>"$lane_c/README"
run_reap --yes "$lane_c"
assert_rc0 "c dirty"
assert_contains "c dirty" "SKIP"
assert_contains "c dirty" "dirty working tree"
assert_exists "c dirty --yes" "$lane_c"

# ---------------------------------------------------------------------------
# (d) clone with non-empty stash -> SKIP;
#     clone with untracked-only .lane stash -> reaped.
# Isolates guard 6 (stash).
# ---------------------------------------------------------------------------
lane_d1="$HOME/w3/lane-d-stash"
clone_lane "$lane_d1"
echo wip >>"$lane_d1/README"
git -C "$lane_d1" stash push -q -m "real work"
run_reap --yes "$lane_d1"
assert_rc0 "d nonempty stash"
assert_contains "d nonempty stash" "SKIP"
assert_contains "d nonempty stash" "stash has real work"
assert_exists "d nonempty stash --yes" "$lane_d1"

lane_d2="$HOME/w3/lane-d-lane-stash"
clone_lane "$lane_d2"
mkdir -p "$lane_d2/.lane"
echo brief >"$lane_d2/.lane/BRIEF.md"
git -C "$lane_d2" stash push -q -u -m "lane noise" -- .lane
run_reap "$lane_d2"
assert_rc0 "d ignorable stash dry-run"
assert_contains "d ignorable stash dry-run" "WOULD REAP"
run_reap --yes "$lane_d2"
assert_rc0 "d ignorable stash --yes"
assert_gone "d ignorable stash --yes" "$lane_d2"

# ---------------------------------------------------------------------------
# (e) path outside allowlist roots -> SKIP even with --yes.
# Isolates guard 2 (allowlist).
# ---------------------------------------------------------------------------
lane_e="$HOME/other/lane-e"
clone_lane "$lane_e"
run_reap --yes "$lane_e"
assert_rc0 "e allowlist"
assert_contains "e allowlist" "SKIP"
assert_contains "e allowlist" "not under allowlisted lane root"
assert_exists "e allowlist --yes" "$lane_e"

# ---------------------------------------------------------------------------
# Extra isolations so deleting any remaining guard fails the suite.
# ---------------------------------------------------------------------------

# Guard 1: not a git directory (under allowlist) -> SKIP, not deleted.
lane_g1="$HOME/w3/not-git"
mkdir -p "$lane_g1"
echo x >"$lane_g1/file"
run_reap --yes "$lane_g1"
assert_rc0 "g1 not-git"
assert_contains "g1 not-git" "SKIP"
assert_contains "g1 not-git" "not a git directory"
assert_exists "g1 not-git --yes" "$lane_g1"

# Guard 3: no origin and no REAP_UPSTREAM -> SKIP.
lane_g3="$HOME/w3/lane-no-origin"
clone_lane "$lane_g3"
git -C "$lane_g3" remote remove origin
run_reap --yes "$lane_g3"
assert_rc0 "g3 no-origin"
assert_contains "g3 no-origin" "SKIP"
assert_contains "g3 no-origin" "no origin remote and REAP_UPSTREAM unset"
assert_exists "g3 no-origin --yes" "$lane_g3"

# Guard 5 ignorable set: untracked .lane/ + REPORT.md must still WOULD REAP.
lane_ign="$HOME/w3/lane-ignorable-dirty"
clone_lane "$lane_ign"
mkdir -p "$lane_ign/.lane" "$lane_ign/.venv"
echo x >"$lane_ign/.lane/BRIEF.md"
echo r >"$lane_ign/REPORT.md"
echo v >"$lane_ign/.venv/x"
run_reap "$lane_ign"
assert_rc0 "g5 ignorable dirty"
assert_contains "g5 ignorable dirty" "WOULD REAP"
assert_exists "g5 ignorable dirty dry-run" "$lane_ign"

# Guard 2 positive: uxw2 and l1 roots are allowlisted.
lane_ux="$HOME/uxw2/lane-ux"
clone_lane "$lane_ux"
run_reap "$lane_ux"
assert_rc0 "g2 uxw2"
assert_contains "g2 uxw2" "WOULD REAP"

lane_l1="$HOME/l1/lane-l1"
clone_lane "$lane_l1"
run_reap "$lane_l1"
assert_rc0 "g2 l1"
assert_contains "g2 l1" "WOULD REAP"

# Guard 2 positive: `w` and `lanes` are lane roots too.
# VMDISK-1: these carried 18G and 9.2G on the VM while the weekly cron swept
# only w3 (1.6G). [RES-07] a reclaimer whose scope does not match what grows is
# not a reclaimer; the disk still reached 96%.
lane_w="$HOME/w/lane-w"
clone_lane "$lane_w"
run_reap "$lane_w"
assert_rc0 "g2 w"
assert_contains "g2 w" "WOULD REAP"

lane_lanes="$HOME/lanes/lane-lanes"
clone_lane "$lane_lanes"
run_reap "$lane_lanes"
assert_rc0 "g2 lanes"
assert_contains "g2 lanes" "WOULD REAP"

# Guard 2 positive: offload lane sandboxes live in ~/grok-sandbox. [RES-07] the
# defaults still read `w3 uxw2 l1 w lanes` while every lane the orchestrator
# created went to ~/grok-sandbox -- 60G across 197 clones, with the cron sweeping
# five roots that no longer grow and reporting success throughout.
lane_gs="$HOME/grok-sandbox/feature-vmreap-1-abc1234"
clone_lane "$lane_gs"
mark_sandbox "$lane_gs"
touch -t 200001010000 "$lane_gs/.workbay-lane-sandbox"

# A destructive sandbox sweep cannot share the materializer lock contract on a
# host without flock. Refuse the whole run before inspecting a lane, while
# leaving the observational dry-run available. Build a complete PATH without
# flock so these cases exercise the macOS behavior on Linux too.
noflock_bin="$WORKDIR/noflock-bin"
mkdir "$noflock_bin"
for command_name in awk bash basename date df dirname du git grep mkdir mv ps \
  realpath rm rmdir sed sort stat touch; do
  ln -s "$(command -v "$command_name")" "$noflock_bin/$command_name"
done
PATH="$noflock_bin" run_reap --yes --all "$HOME/grok-sandbox"
if [[ "$rc" -eq 2 ]]; then pass "grok-sandbox no-flock destructive exit 2"
else fail "grok-sandbox no-flock destructive expected exit 2 got $rc; out=$out"; fi
assert_contains "grok-sandbox no-flock destructive" \
  "reap-lane: flock is required for destructive sandbox sweeps"
assert_exists "grok-sandbox no-flock destructive" "$lane_gs"
PATH="$noflock_bin" run_reap --all "$HOME/grok-sandbox"
assert_rc0 "grok-sandbox no-flock dry-run"
assert_contains "grok-sandbox no-flock dry-run" "WOULD REAP $lane_gs"
assert_exists "grok-sandbox no-flock dry-run" "$lane_gs"

# Eligibility-reason cases need a deterministic lane-lock result on both Linux
# and macOS. This minimal shim also handles the whole-sweep lock and unlock.
flock_success_bin="$WORKDIR/flock-success-bin"
mkdir "$flock_success_bin"
cat >"$flock_success_bin/flock" <<'FLOCK_SUCCESS'
#!/bin/sh
exit 0
FLOCK_SUCCESS
chmod +x "$flock_success_bin/flock"

# ...and widening the roots must not come from loosening the matcher: the
# segment-exact guard still refuses a sibling that merely shares the prefix.
lane_gs_like="$HOME/grok-sandbox-old/lane-x"
clone_lane "$lane_gs_like"
run_reap --yes "$lane_gs_like"
assert_rc0 "g2 grok-sandbox prefix-not-root"
assert_contains "g2 grok-sandbox prefix-not-root" "not under allowlisted lane root"
assert_exists "g2 grok-sandbox prefix-not-root kept" "$lane_gs_like"

# The roots are an allowlist, not a prefix match: a sibling whose name merely
# starts with an allowlisted root must still be refused. Without an exact
# segment match, `w` would admit ~/work, ~/website, ~/wp-content ...
lane_wlike="$HOME/wordpress-data/lane-x"
clone_lane "$lane_wlike"
run_reap --yes "$lane_wlike"
assert_rc0 "g2 prefix-not-root"
assert_contains "g2 prefix-not-root" "not under allowlisted lane root"
assert_exists "g2 prefix-not-root kept" "$lane_wlike"

# A root that is itself a clone must be refused: reaping $HOME/w would take
# every sibling lane with it. Asserted on the *reason*, and against a real git
# clone -- a bare "SKIP" on a non-git directory passes for the wrong reason and
# lets the depth guard be deleted unnoticed.
sole_root="$HOME/soleroot"
clone_lane "$sole_root"
REAP_LANE_ROOTS="soleroot" run_reap --yes "$sole_root"
assert_contains "g2 root itself" "not under allowlisted lane root"
assert_exists "g2 root itself kept" "$sole_root"

# The roots must be overridable so a new lane root does not require a code
# change to reclaim (and so the cron can name exactly what it sweeps).
lane_custom="$HOME/scratchpad/lane-c"
clone_lane "$lane_custom"
REAP_LANE_ROOTS="scratchpad" run_reap "$lane_custom"
assert_rc0 "g2 override"
assert_contains "g2 override" "WOULD REAP"

# An override must REPLACE the defaults, not extend them: an operator who
# narrows the roots for a one-off sweep must not silently still reap w3.
lane_default="$HOME/w3/lane-still-default"
clone_lane "$lane_default"
REAP_LANE_ROOTS="scratchpad" run_reap --yes "$lane_default"
assert_contains "g2 override replaces" "not under allowlisted lane root"
assert_exists "g2 override replaces kept" "$lane_default"

# --- archive-then-reap -------------------------------------------------------
# VMDISK-1. Ancestry cannot answer "is this merged?" for a wave that landed by
# squash or rebase: the lane's commits are never ancestors of main, so the guard
# skips forever and the reclaimer frees nothing. The VM sat at 94% with ~85
# lanes, git objects totalling 239M and the rest being duplicated working-tree
# checkouts (~500M each).
#
# --archive-to sidesteps the question. Push every local ref into a keep-repo
# first and the commits survive whether or not they ever reached main, so
# deleting the *checkout* cannot lose work. The guard then only has to protect
# what has no commit behind it: an uncommitted tree, and a stash.

ARCHIVE="$WORKDIR/archive.git"
git init --bare --quiet "$ARCHIVE"

archive_has() {  # $1 label, $2 ref, $3 expected sha
  local got
  got="$(git -C "$ARCHIVE" rev-parse --verify --quiet "$2" || true)"
  if [[ "$got" == "$3" ]]; then pass "$1 archived $2"
  else fail "$1: $2 is '$got', expected '$3'"; fi
}

archive_lacks_namespace() {  # $1 label, $2 namespace
  local refs
  refs="$(git -C "$ARCHIVE" for-each-ref --format='%(refname)' "refs/lanes/$2")"
  if [[ -z "$refs" ]]; then pass "$1 did not archive"
  else fail "$1 unexpectedly created archive refs: $refs"; fi
}

generation_of() {  # $1 repo
  git -C "$1" rev-list --max-parents=0 HEAD | sort | sed -n '1p'
}

# Git safety reads fail closed. A broken or unreadable index must never be
# interpreted as a clean checkout, and an unreadable stash list must never be
# interpreted as an empty stash.
git_guard_bin="$WORKDIR/git-guard-bin"
mkdir "$git_guard_bin"
cat >"$git_guard_bin/git" <<'GIT_GUARD'
#!/bin/sh
case " $* " in
  *" status --porcelain "*|*" status --porcelain=v1 "*)
    echo "simulated unreadable index" >&2
    exit 128
    ;;
esac
exec "$REAL_GIT" "$@"
GIT_GUARD
chmod +x "$git_guard_bin/git"
lane_status_fail="$HOME/w/lane-status-fail"
clone_lane "$lane_status_fail"
REAL_GIT="$(command -v git)" PATH="$git_guard_bin:$PATH" REAP_MIN_AGE_SEC=0 \
  run_reap --archive-to "$ARCHIVE" "$lane_status_fail"
assert_contains "git status failure" "could not read git status"
assert_not_contains "git status failure" "WOULD REAP"
assert_exists "git status failure" "$lane_status_fail"

stash_guard_bin="$WORKDIR/stash-guard-bin"
mkdir "$stash_guard_bin"
cat >"$stash_guard_bin/git" <<'STASH_GUARD'
#!/bin/sh
case " $* " in
  *" stash list "*)
    echo "simulated unreadable stash" >&2
    exit 128
    ;;
esac
exec "$REAL_GIT" "$@"
STASH_GUARD
chmod +x "$stash_guard_bin/git"
lane_stash_fail="$HOME/w/lane-stash-fail"
clone_lane "$lane_stash_fail"
mkdir "$lane_stash_fail/.lane"
echo metadata >"$lane_stash_fail/.lane/meta"
git -C "$lane_stash_fail" stash push -q -u -m metadata
REAL_GIT="$(command -v git)" PATH="$stash_guard_bin:$PATH" REAP_MIN_AGE_SEC=0 \
  run_reap --archive-to "$ARCHIVE" "$lane_stash_fail"
assert_contains "git stash failure" "could not read git status"
assert_not_contains "git stash failure" "WOULD REAP"
assert_exists "git stash failure" "$lane_stash_fail"

# The archive must outlive the lane. A local archive nested below the checkout
# would accept and verify every ref, then disappear in the same rm -rf.
lane_nested_archive="$HOME/w3/nested-archive"
clone_lane "$lane_nested_archive"
nested_archive="$lane_nested_archive/.git/archive.git"
git init --bare --quiet "$nested_archive"
REAP_MIN_AGE_SEC=0 run_reap --yes --archive-to "$nested_archive" "$lane_nested_archive"
assert_rc0 "archive destination inside lane"
assert_contains "archive destination inside lane" "archive destination is inside lane"
assert_exists "archive destination inside lane" "$lane_nested_archive"

# Localhost file URLs are local paths, including after percent decoding. They
# must pass through the same containment check as a plain filesystem path.
lane_nested_localhost="$HOME/w3/nested-localhost-archive"
clone_lane "$lane_nested_localhost"
nested_localhost_archive="$lane_nested_localhost/.git/archive.git"
git init --bare --quiet "$nested_localhost_archive"
nested_localhost_url="file://localhost${lane_nested_localhost}/.git/archive%2egit"
REAP_MIN_AGE_SEC=0 run_reap --yes --archive-to "$nested_localhost_url" \
  "$lane_nested_localhost"
assert_rc0 "localhost archive destination inside lane"
assert_contains "localhost archive destination inside lane" \
  "archive destination is inside lane"
assert_exists "localhost archive destination inside lane" "$lane_nested_localhost"

run_reap --yes --archive-to "file://archive-host.invalid/archive.git" \
  "$lane_nested_localhost"
if [[ "$rc" -ne 0 ]]; then
  pass "non-local file URL authority exits nonzero"
else
  fail "non-local file URL authority unexpectedly exited zero; out=$out"
fi
assert_contains "non-local file URL authority" "unsupported file URL authority"
assert_exists "non-local file URL authority" "$lane_nested_localhost"

# The generic lane sweep must honor the remote sandbox lifecycle before it
# archives or deletes anything: marker TTL, occupancy lease, and per-lane lock.
lane_gs_fresh="$HOME/grok-sandbox/feature-fresh-abc12345"
clone_lane "$lane_gs_fresh"
mark_sandbox "$lane_gs_fresh"
PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_fresh"
assert_rc0 "grok-sandbox fresh marker"
assert_contains "grok-sandbox fresh marker" "sandbox marker has not reached TTL"
assert_exists "grok-sandbox fresh marker" "$lane_gs_fresh"
archive_lacks_namespace "grok-sandbox fresh marker" "grok-sandbox/${lane_gs_fresh##*/}"

if command -v flock >/dev/null 2>&1; then
  # Remove the earlier stale canary, then prove a sweep containing only a
  # fresh sandbox is not misreported as zero-reclaim staleness.
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs"
  assert_rc0 "grok-sandbox stale marker"
  assert_gone "grok-sandbox stale marker" "$lane_gs"
  REAP_DF_ALERT_PCT=0 run_reap --yes --archive-to "$ARCHIVE" --all "$HOME/grok-sandbox"
  assert_rc0 "grok-sandbox fresh-only sweep"
  assert_exists "grok-sandbox fresh-only sweep" "$lane_gs_fresh"

  # Marker-less directories are operator-owned, even when old and git-backed.
  # They must never be promoted into the managed sandbox lifecycle by mtime.
  lane_gs_legacy_dirty="$HOME/grok-sandbox/feature-legacy-dirty-abc12345"
  clone_lane "$lane_gs_legacy_dirty"
  echo dirty >>"$lane_gs_legacy_dirty/README"
  touch -t 200001010000 "$lane_gs_legacy_dirty"
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_legacy_dirty"
  assert_contains "grok-sandbox unmarked dirty" \
    "unmarked sandbox dir; operator review"
  assert_exists "grok-sandbox unmarked dirty" "$lane_gs_legacy_dirty"
  if [[ ! -e "$lane_gs_legacy_dirty/.workbay-lane-sandbox" ]]; then
    pass "grok-sandbox unmarked dirty did not create marker"
  else
    fail "grok-sandbox unmarked dirty created marker"
  fi

  # The materializer lock must precede the destructive eligibility checks. A
  # writer that dirties the checkout as that lock is acquired must be seen by
  # the dirty-tree guard, not absorbed into the deletion-safety snapshot.
  lane_gs_lock_race="$HOME/grok-sandbox/feature-lock-race-abc12345"
  clone_lane "$lane_gs_lock_race"
  mark_sandbox "$lane_gs_lock_race"
  touch -t 200001010000 "$lane_gs_lock_race/.workbay-lane-sandbox"
  lock_race_bin="$WORKDIR/lock-race-bin"
  mkdir "$lock_race_bin"
  cat >"$lock_race_bin/flock" <<'LOCK_RACE_FLOCK'
#!/usr/bin/env bash
set -e
"$REAL_FLOCK" "$@"
if [[ "${1:-}" == "-n" && "${2:-}" == "8" && ! -e "$LOCK_RACE_ONCE" ]]; then
  : >"$LOCK_RACE_ONCE"
  printf 'writer arrived\n' >"$LOCK_RACE_LANE/LOCK_RACE_WORK"
fi
LOCK_RACE_FLOCK
  chmod +x "$lock_race_bin/flock"
  REAL_FLOCK="$(command -v flock)" LOCK_RACE_LANE="$lane_gs_lock_race" \
    LOCK_RACE_ONCE="$WORKDIR/lock-race-once" PATH="$lock_race_bin:$PATH" \
    run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_lock_race"
  assert_rc0 "grok-sandbox lock-before-eligibility race"
  assert_contains "grok-sandbox lock-before-eligibility race" "dirty working tree"
  assert_exists "grok-sandbox lock-before-eligibility race" "$lane_gs_lock_race"
  assert_path_exists "grok-sandbox lock-before-eligibility writer work" \
    "$lane_gs_lock_race/LOCK_RACE_WORK"

  lane_gs_legacy="$HOME/grok-sandbox/feature-legacy-abc12345"
  clone_lane "$lane_gs_legacy"
  legacy_key="${lane_gs_legacy##*/}"
  : >"$HOME/grok-sandbox/.lane-lock-$legacy_key"
  printf 'issued=1\nexpiry=2\n' >"$HOME/grok-sandbox/.lane-live-$legacy_key"
  mkdir "$HOME/grok-sandbox/.venv-lane-$legacy_key"
  : >"$HOME/grok-sandbox/.venv-sync-stamp-$legacy_key"
  touch -t 200001010000 "$lane_gs_legacy"
  run_reap --archive-to "$ARCHIVE" "$lane_gs_legacy"
  assert_rc0 "grok-sandbox unmarked dry-run"
  assert_contains "grok-sandbox unmarked dry-run" \
    "unmarked sandbox dir; operator review"
  assert_not_contains "grok-sandbox unmarked dry-run" "WOULD REAP"
  assert_exists "grok-sandbox unmarked dry-run" "$lane_gs_legacy"
  if [[ ! -e "$lane_gs_legacy/.workbay-lane-sandbox" ]]; then
    pass "grok-sandbox unmarked dry-run did not create marker"
  else
    fail "grok-sandbox unmarked dry-run created marker"
  fi
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_legacy"
  assert_rc0 "grok-sandbox unmarked destructive"
  assert_contains "grok-sandbox unmarked destructive" \
    "unmarked sandbox dir; operator review"
  assert_exists "grok-sandbox unmarked destructive" "$lane_gs_legacy"
  if [[ -e "$HOME/grok-sandbox/.lane-lock-$legacy_key" ]]; then
    pass "grok-sandbox unmarked lane lock inode retained"
  else
    fail "grok-sandbox unmarked lane lock inode was unlinked"
  fi
  assert_path_exists "grok-sandbox unmarked lease" "$HOME/grok-sandbox/.lane-live-$legacy_key"
  assert_exists "grok-sandbox unmarked venv" "$HOME/grok-sandbox/.venv-lane-$legacy_key"
  assert_path_exists "grok-sandbox unmarked sync stamp" "$HOME/grok-sandbox/.venv-sync-stamp-$legacy_key"

  # A lock absent at the eligibility check can be materialized after archive
  # and before rm. The reaper must create-and-lock the stable path itself, then
  # prove the pathname still names its fd immediately before deletion.
  lane_gs_late_lock="$HOME/grok-sandbox/feature-late-lock-abc12345"
  clone_lane "$lane_gs_late_lock"
  mark_sandbox "$lane_gs_late_lock"
  touch -t 200001010000 "$lane_gs_late_lock/.workbay-lane-sandbox"
  late_key="${lane_gs_late_lock##*/}"
  late_lock="$HOME/grok-sandbox/.lane-lock-$late_key"
  late_lease="$HOME/grok-sandbox/.lane-live-$late_key"
  late_venv="$HOME/grok-sandbox/.venv-lane-$late_key"
  late_trigger="$WORKDIR/late-lock-trigger"
  late_ready="$WORKDIR/late-lock-ready"
  late_release="$WORKDIR/late-lock-release"
  late_exited="$WORKDIR/late-lock-exited"
  late_du_bin="$WORKDIR/late-lock-du-bin"
  mkdir "$late_du_bin"
  cat >"$late_du_bin/du" <<'LATE_LOCK_DU'
#!/usr/bin/env bash
set -e
if [[ "$*" == *"$LATE_LANE"* && ! -e "$LATE_TRIGGER" ]]; then
  : >"$LATE_TRIGGER"
  attempt=0
  while [[ ! -e "$LATE_READY" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  [[ -e "$LATE_READY" ]] || exit 124
fi
exec "$REAL_DU" "$@"
LATE_LOCK_DU
  chmod +x "$late_du_bin/du"
  (
    trap ': >"$late_exited"' EXIT
    attempt=0
    while [[ ! -e "$late_trigger" && "$attempt" -lt 1000 ]]; do
      sleep 0.01
      attempt=$((attempt + 1))
    done
    [[ -e "$late_trigger" ]] || exit 124
    rm -f "$late_lock"
    exec 7>>"$late_lock"
    flock 7
    printf 'issued=1\nexpiry=2\n' >"$late_lease"
    mkdir "$late_venv"
    : >"$late_ready"
    attempt=0
    while [[ ! -e "$late_release" && "$attempt" -lt 1000 ]]; do
      sleep 0.01
      attempt=$((attempt + 1))
    done
    [[ -e "$late_release" ]] || exit 124
  ) &
  late_materializer_pid=$!
  LATE_LANE="$lane_gs_late_lock" LATE_TRIGGER="$late_trigger" \
    LATE_READY="$late_ready" REAL_DU="$(command -v du)" \
    PATH="$late_du_bin:$PATH" \
    run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_late_lock"
  assert_rc0 "grok-sandbox late lane lock"
  assert_contains "grok-sandbox late lane lock" "lane lock replaced"
  assert_exists "grok-sandbox late lane lock lane" "$lane_gs_late_lock"
  assert_path_exists "grok-sandbox late lane lock lease" "$late_lease"
  assert_exists "grok-sandbox late lane lock venv" "$late_venv"
  : >"$late_release"
  wait_for_background_pid "$late_materializer_pid" "$late_exited" \
    "grok-sandbox late lane lock" || true

  # If a materializer replaces the path with a newly locked inode after the
  # checkout disappears, sibling cleanup must not unlink that new lock.
  lane_gs_recreated_lock="$HOME/grok-sandbox/feature-recreated-lock-abc12345"
  clone_lane "$lane_gs_recreated_lock"
  mark_sandbox "$lane_gs_recreated_lock"
  touch -t 200001010000 "$lane_gs_recreated_lock/.workbay-lane-sandbox"
  recreated_key="${lane_gs_recreated_lock##*/}"
  recreated_lock="$HOME/grok-sandbox/.lane-lock-$recreated_key"
  recreated_trigger="$WORKDIR/recreated-lock-trigger"
  recreated_ready="$WORKDIR/recreated-lock-ready"
  recreated_release="$WORKDIR/recreated-lock-release"
  recreated_exited="$WORKDIR/recreated-lock-exited"
  : >"$recreated_lock"
  recreated_rm_bin="$WORKDIR/recreated-rm-bin"
  mkdir "$recreated_rm_bin"
  cat >"$recreated_rm_bin/rm" <<'RECREATED_RM'
#!/usr/bin/env bash
set -e
for arg in "$@"; do
  if [[ "$arg" == "$RECREATED_LANE" ]]; then
    "$REAL_RM" "$@"
    : >"$RECREATED_TRIGGER"
    attempt=0
    while [[ ! -e "$RECREATED_READY" && "$attempt" -lt 1000 ]]; do
      sleep 0.01
      attempt=$((attempt + 1))
    done
    if [[ ! -e "$RECREATED_READY" ]]; then
      echo "FAIL: recreated lane lock materializer did not become ready" >&2
      exit 124
    fi
    exit 0
  fi
done
exec "$REAL_RM" "$@"
RECREATED_RM
  chmod +x "$recreated_rm_bin/rm"
  (
    trap ': >"$recreated_exited"' EXIT
    attempt=0
    while [[ ! -e "$recreated_trigger" && "$attempt" -lt 1000 ]]; do
      sleep 0.01
      attempt=$((attempt + 1))
    done
    if [[ ! -e "$recreated_trigger" ]]; then
      exit 124
    fi
    "$(command -v rm)" -f "$recreated_lock"
    exec 7>"$recreated_lock"
    flock 7
    printf 'issued=1\nexpiry=2\n' >"$HOME/grok-sandbox/.lane-live-$recreated_key"
    mkdir "$HOME/grok-sandbox/.venv-lane-$recreated_key"
    : >"$HOME/grok-sandbox/.venv-sync-stamp-$recreated_key"
    : >"$recreated_ready"
    attempt=0
    while [[ ! -e "$recreated_release" && "$attempt" -lt 1000 ]]; do
      sleep 0.01
      attempt=$((attempt + 1))
    done
    [[ -e "$recreated_release" ]] || exit 124
  ) &
  recreated_materializer_pid=$!
  RECREATED_LANE="$lane_gs_recreated_lock" \
    RECREATED_TRIGGER="$recreated_trigger" RECREATED_READY="$recreated_ready" \
    REAL_RM="$(command -v rm)" PATH="$recreated_rm_bin:$PATH" \
    run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_recreated_lock"
  assert_rc0 "grok-sandbox recreated lane lock"
  assert_gone "grok-sandbox recreated lane lock lane" "$lane_gs_recreated_lock"
  if [[ -e "$recreated_lock" ]]; then
    pass "grok-sandbox recreated lane lock inode retained"
  else
    fail "grok-sandbox recreated lane lock inode was unlinked"
  fi
  assert_contains "grok-sandbox recreated lane lock" \
    "lane lock replaced after removal; sibling cleanup skipped"
  assert_summary_counts "grok-sandbox recreated lane lock" 1 1 0
  if grep -qF "$lane_gs_recreated_lock" "$HOME/reap-lane.log"; then
    pass "grok-sandbox recreated lane lock logged removal"
  else
    fail "grok-sandbox recreated lane lock missing removal log"
  fi
  assert_path_exists "grok-sandbox recreated lane lease" \
    "$HOME/grok-sandbox/.lane-live-$recreated_key"
  assert_exists "grok-sandbox recreated lane venv" \
    "$HOME/grok-sandbox/.venv-lane-$recreated_key"
  assert_path_exists "grok-sandbox recreated lane sync stamp" \
    "$HOME/grok-sandbox/.venv-sync-stamp-$recreated_key"
  : >"$recreated_release"
  wait_for_background_pid "$recreated_materializer_pid" "$recreated_exited" \
    "grok-sandbox recreated lane lock" || true
else
  skip_case "grok-sandbox stale marker and fresh-only sweep"
  skip_case "grok-sandbox unmarked dirty directory"
  skip_case "grok-sandbox lock-before-eligibility race"
  skip_case "grok-sandbox unmarked old directory"
  skip_case "grok-sandbox late lock replacement"
  skip_case "grok-sandbox post-rm lock replacement"
fi

lane_gs_leased="$HOME/grok-sandbox/feature-leased-abc12345"
clone_lane "$lane_gs_leased"
mark_sandbox "$lane_gs_leased"
touch -t 200001010000 "$lane_gs_leased/.workbay-lane-sandbox"
now_epoch="$(date +%s)"
printf 'pid=%s\nissued=%s\nexpiry=%s\n' "$$" "$now_epoch" "$((now_epoch + 3600))" \
  >"$HOME/grok-sandbox/.lane-live-${lane_gs_leased##*/}"
PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_leased"
assert_rc0 "grok-sandbox live lease"
assert_contains "grok-sandbox live lease" "sandbox lease is live"
assert_exists "grok-sandbox live lease" "$lane_gs_leased"
archive_lacks_namespace "grok-sandbox live lease" "grok-sandbox/${lane_gs_leased##*/}"

lane_gs_locked="$HOME/grok-sandbox/feature-locked-abc12345"
clone_lane "$lane_gs_locked"
mark_sandbox "$lane_gs_locked"
touch -t 200001010000 "$lane_gs_locked/.workbay-lane-sandbox"
flock_contention_bin="$WORKDIR/flock-contention-bin"
mkdir "$flock_contention_bin"
cat >"$flock_contention_bin/flock" <<'FLOCK_CONTENTION'
#!/bin/sh
if [ "${1:-}" = "-n" ] && [ "${2:-}" = "8" ]; then
  exit 1
fi
exit 0
FLOCK_CONTENTION
chmod +x "$flock_contention_bin/flock"
PATH="$flock_contention_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_locked"
assert_rc0 "grok-sandbox lane lock"
assert_contains "grok-sandbox lane lock" "lane lock contended"
assert_not_contains "grok-sandbox lane lock" "unverifiable"
assert_exists "grok-sandbox lane lock" "$lane_gs_locked"
archive_lacks_namespace "grok-sandbox lane lock" "grok-sandbox/${lane_gs_locked##*/}"

# The contention assertion must depend on flock rejecting fd 8, not on the
# pathname-to-fd identity check failing afterward. With the same lane and an
# available lock, eligibility should supply the reason instead.
touch "$lane_gs_locked/.workbay-lane-sandbox"
PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_locked"
assert_rc0 "grok-sandbox available lane lock"
assert_contains "grok-sandbox available lane lock" \
  "sandbox marker has not reached TTL"
assert_not_contains "grok-sandbox available lane lock" "lane lock contended"
assert_exists "grok-sandbox available lane lock" "$lane_gs_locked"
archive_lacks_namespace "grok-sandbox available lane lock" \
  "grok-sandbox/${lane_gs_locked##*/}"

# If either inode lookup is unavailable, destructive cleanup must fail closed.
# The stat shim delegates every other query used by the reaper.
lane_gs_unverified_lock="$HOME/grok-sandbox/feature-unverified-lock-abc12345"
clone_lane "$lane_gs_unverified_lock"
mark_sandbox "$lane_gs_unverified_lock"
touch -t 200001010000 "$lane_gs_unverified_lock/.workbay-lane-sandbox"
unverified_lock="$HOME/grok-sandbox/.lane-lock-${lane_gs_unverified_lock##*/}"
: >"$unverified_lock"
stat_failure_bin="$WORKDIR/stat-failure-bin"
mkdir "$stat_failure_bin"
cat >"$stat_failure_bin/stat" <<'STAT_FAILURE'
#!/bin/sh
for arg in "$@"; do
  if [ "$arg" = "/dev/fd/8" ]; then
    exit 1
  fi
done
exec "$REAL_STAT" "$@"
STAT_FAILURE
chmod +x "$stat_failure_bin/stat"
REAL_STAT="$(command -v stat)" PATH="$flock_success_bin:$stat_failure_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_unverified_lock"
assert_rc0 "grok-sandbox unverifiable lane lock"
assert_contains "grok-sandbox unverifiable lane lock" \
  "lane lock unverifiable: could not stat open lock fd"
assert_exists "grok-sandbox unverifiable lane lock" "$lane_gs_unverified_lock"
archive_lacks_namespace "grok-sandbox unverifiable lane lock" \
  "grok-sandbox/${lane_gs_unverified_lock##*/}"

# Replacing the stable lock pathname after fd 8 is opened must be detected even
# when flock itself reports success.
lane_gs_replaced_at_lock="$HOME/grok-sandbox/feature-replaced-at-lock-abc12345"
clone_lane "$lane_gs_replaced_at_lock"
mark_sandbox "$lane_gs_replaced_at_lock"
touch -t 200001010000 "$lane_gs_replaced_at_lock/.workbay-lane-sandbox"
replaced_at_lock="$HOME/grok-sandbox/.lane-lock-${lane_gs_replaced_at_lock##*/}"
: >"$replaced_at_lock"
flock_replace_bin="$WORKDIR/flock-replace-bin"
mkdir "$flock_replace_bin"
cat >"$flock_replace_bin/flock" <<'FLOCK_REPLACE'
#!/bin/sh
if [ "${1:-}" = "-n" ] && [ "${2:-}" = "8" ]; then
  mv "$REPLACE_LOCK" "$REPLACE_LOCK.opened"
  : >"$REPLACE_LOCK"
fi
exit 0
FLOCK_REPLACE
chmod +x "$flock_replace_bin/flock"
REPLACE_LOCK="$replaced_at_lock" PATH="$flock_replace_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_replaced_at_lock"
assert_rc0 "grok-sandbox replaced-at-acquire lane lock"
assert_contains "grok-sandbox replaced-at-acquire lane lock" \
  "lane lock replaced"
assert_exists "grok-sandbox replaced-at-acquire lane lock" \
  "$lane_gs_replaced_at_lock"
archive_lacks_namespace "grok-sandbox replaced-at-acquire lane lock" \
  "grok-sandbox/${lane_gs_replaced_at_lock##*/}"

# remote_agent.sh allows the managed sandbox root to move. The reaper must
# resolve and recognize that configured root so marker, lock, lease, and TTL
# guards cannot be bypassed by falling into the generic one-hour path.
remote_agent_root="$HOME/w/custom-agent-sandboxes"
lane_custom_agent="$remote_agent_root/feature-custom-agent-abc12345"
clone_lane "$lane_custom_agent"
mark_sandbox "$lane_custom_agent"
WORKBAY_REMOTE_AGENT_ROOT="$remote_agent_root/../custom-agent-sandboxes" \
  PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_custom_agent"
assert_rc0 "custom remote-agent root"
assert_contains "custom remote-agent root" "sandbox marker has not reached TTL"
assert_exists "custom remote-agent root" "$lane_custom_agent"

WORKBAY_REMOTE_AGENT_ROOT="$remote_agent_root" PATH="$noflock_bin" \
  run_reap --yes "$lane_custom_agent"
if [[ "$rc" -eq 2 ]]; then pass "custom remote-agent root no-flock exit 2"
else fail "custom remote-agent root no-flock expected exit 2 got $rc; out=$out"; fi
assert_contains "custom remote-agent root no-flock" \
  "reap-lane: flock is required for destructive sandbox sweeps"

# A configured agent root is an explicit deletion boundary, not merely a hint
# that enables sandbox locking inside one of the default roots.
remote_sibling_root="$HOME/grok-sandbox-altcontext"
lane_remote_direct="$remote_sibling_root/feature-remote-direct-abc12345"
clone_lane "$lane_remote_direct"
mark_sandbox "$lane_remote_direct"
WORKBAY_REMOTE_AGENT_ROOT="$remote_sibling_root" PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_remote_direct"
assert_rc0 "remote-agent explicit root direct"
assert_contains "remote-agent explicit root direct" "sandbox marker has not reached TTL"
assert_exists "remote-agent explicit root direct" "$lane_remote_direct"

remote_all_root="$HOME/grok-sandbox-altall"
lane_remote_all="$remote_all_root/feature-remote-all-abc12345"
clone_lane "$lane_remote_all"
mark_sandbox "$lane_remote_all"
touch -t 200001010000 "$lane_remote_all/.workbay-lane-sandbox"
WORKBAY_REMOTE_AGENT_ROOT="$remote_all_root" PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" --all "$remote_all_root"
assert_rc0 "remote-agent explicit root all"
assert_gone "remote-agent explicit root all" "$lane_remote_all"

outside_remote_root="${HOME}-outside-agent-root"
lane_outside_remote="$outside_remote_root/feature-outside-abc12345"
clone_lane "$lane_outside_remote"
mark_sandbox "$lane_outside_remote"
WORKBAY_REMOTE_AGENT_ROOT="$outside_remote_root" PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_outside_remote"
assert_contains "remote-agent root outside HOME" \
  "WORKBAY_REMOTE_AGENT_ROOT must be strictly below HOME"
assert_exists "remote-agent root outside HOME" "$lane_outside_remote"

unmarked_root="$HOME/grok-sandbox-unmarked"
lane_unmarked_pressure="$unmarked_root/feature-unmarked-abc12345"
clone_lane "$lane_unmarked_pressure"
WORKBAY_REMOTE_AGENT_ROOT="$unmarked_root" REAP_DF_ALERT_PCT=0 \
  PATH="$flock_success_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" --all "$unmarked_root"
if [[ "$rc" -eq 4 ]]; then pass "unmarked sandbox freshness alert exit 4"
else fail "unmarked sandbox freshness alert expected exit 4 got $rc; out=$out"; fi
assert_contains "unmarked sandbox freshness alert" "unmarked sandbox dir; operator review"
assert_exists "unmarked sandbox freshness alert" "$lane_unmarked_pressure"

# A contended lock prevents the TTL read, so the lane still counts as a
# freshness candidate. Under pressure an all-root sweep must therefore alert.
remote_locked_root="$HOME/w/custom-agent-locked"
lane_custom_locked="$remote_locked_root/feature-custom-locked-abc12345"
clone_lane "$lane_custom_locked"
mark_sandbox "$lane_custom_locked"
touch -t 200001010000 "$lane_custom_locked/.workbay-lane-sandbox"
WORKBAY_REMOTE_AGENT_ROOT="$remote_locked_root" REAP_DF_ALERT_PCT=0 \
  PATH="$flock_contention_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" --all "$remote_locked_root"
if [[ "$rc" -eq 4 ]]; then pass "contended sandbox freshness alert exit 4"
else fail "contended sandbox freshness alert expected exit 4 got $rc; out=$out"; fi
assert_contains "contended sandbox freshness alert" "lane lock contended"
assert_summary "contended sandbox freshness alert" 1 0 1 0
assert_exists "contended sandbox freshness alert" "$lane_custom_locked"

# A dry run is observational only: it must neither delete the checkout nor
# create archive refs (including an anchor ref for a linked worktree).
lane_dry_archive="$HOME/w/lane-dry-archive"
clone_lane "$lane_dry_archive"
REAP_MIN_AGE_SEC=0 run_reap --archive-to "$ARCHIVE" "$lane_dry_archive"
assert_rc0 "archive dry-run"
assert_contains "archive dry-run" "WOULD REAP"
assert_exists "archive dry-run" "$lane_dry_archive"
archive_lacks_namespace "archive dry-run" "w/lane-dry-archive"

# Non-sandbox archive reaps need a minimum age because these roots have no
# materializer lease/lock contract. Use the newest checkout/git timestamp.
lane_recent="$HOME/w/lane-recent"
clone_lane "$lane_recent"
run_reap --yes --archive-to "$ARCHIVE" "$lane_recent"
assert_contains "archive recent lane" "lane is too recent"
assert_exists "archive recent lane" "$lane_recent"
touch -t 200001010000 "$lane_recent" "$lane_recent/.git/index" "$lane_recent/.git/HEAD"
recent_generation="$(generation_of "$lane_recent")"
recent_sha="$(git -C "$lane_recent" rev-parse HEAD)"
run_reap --yes --archive-to "$ARCHIVE" "$lane_recent"
assert_gone "archive aged lane" "$lane_recent"
archive_has "archive aged lane" "refs/lanes/w/lane-recent/$recent_generation/main" "$recent_sha"

# Remaining fixtures isolate archive behavior, independently of the age gate.
export REAP_MIN_AGE_SEC=0

# Unmerged work is reaped once it is archived -- and every branch lands.
lane_ar="$HOME/w/lane-archive"
clone_lane "$lane_ar"
echo "unmerged" >"$lane_ar/UNMERGED"
git -C "$lane_ar" add UNMERGED
git -C "$lane_ar" commit -q -m "work that never reached main"
git -C "$lane_ar" branch second-branch
ar_sha="$(git -C "$lane_ar" rev-parse HEAD)"
ar_generation="$(generation_of "$lane_ar")"
run_reap --yes --archive-to "$ARCHIVE" "$lane_ar"
assert_rc0 "archive reap"
assert_gone "archive reap" "$lane_ar"
archive_has "archive reap" "refs/lanes/w/lane-archive/$ar_generation/main" "$ar_sha"
archive_has "archive reap" "refs/lanes/w/lane-archive/$ar_generation/second-branch" "$ar_sha"

# A local tag can be the only ref retaining a commit. Preserve the tag object
# itself (including annotated-tag metadata), not merely its peeled commit.
lane_tag="$HOME/w/lane-tag-only"
clone_lane "$lane_tag"
echo "tag only" >"$lane_tag/TAG_ONLY"
git -C "$lane_tag" add TAG_ONLY
git -C "$lane_tag" commit -q -m "commit retained only by tag"
git -C "$lane_tag" tag -a tag-only -m "retain tag-only commit"
tag_object="$(git -C "$lane_tag" rev-parse refs/tags/tag-only)"
git -C "$lane_tag" reset -q --hard HEAD^
tag_generation="$(generation_of "$lane_tag")"
run_reap --yes --archive-to "$ARCHIVE" "$lane_tag"
assert_rc0 "archive tag-only commit"
assert_gone "archive tag-only commit" "$lane_tag"
archive_has "archive tag-only commit" \
  "refs/lanes/w/lane-tag-only/$tag_generation/refs/tags/tag-only" "$tag_object"

# Without --archive-to the old guard still holds: unmerged work is never
# deleted just because a flag was forgotten.
lane_nar="$HOME/w/lane-noarchive"
clone_lane "$lane_nar"
echo "unmerged" >"$lane_nar/UNMERGED"
git -C "$lane_nar" add UNMERGED
git -C "$lane_nar" commit -q -m "work that never reached main"
run_reap --yes "$lane_nar"
assert_contains "no-archive still guards" "unmerged local work"
assert_exists "no-archive still guards" "$lane_nar"

# Non-archive mode must consider all refs and reflog tips, not only local
# branches and HEAD. Each fixture resets HEAD to upstream so those old checks
# alone would incorrectly deem the checkout disposable.
lane_nar_tag="$HOME/w/lane-noarchive-tag-only"
clone_lane "$lane_nar_tag"
echo "tag-only local work" >"$lane_nar_tag/TAG_ONLY"
git -C "$lane_nar_tag" add TAG_ONLY
git -C "$lane_nar_tag" commit -q -m "tag-only local work"
git -C "$lane_nar_tag" tag -a local-only -m "retain local-only commit"
git -C "$lane_nar_tag" reset -q --hard HEAD^
run_reap --yes "$lane_nar_tag"
assert_contains "no-archive tag-only work" "unmerged local work"
assert_exists "no-archive tag-only work" "$lane_nar_tag"

lane_nar_reflog="$HOME/w/lane-noarchive-reflog-only"
clone_lane "$lane_nar_reflog"
echo "reflog-only local work" >"$lane_nar_reflog/REFLOG_ONLY"
git -C "$lane_nar_reflog" add REFLOG_ONLY
git -C "$lane_nar_reflog" commit -q -m "reflog-only local work"
git -C "$lane_nar_reflog" reset -q --hard HEAD^
run_reap --yes "$lane_nar_reflog"
assert_contains "no-archive reflog-only work" "unmerged local work"
assert_exists "no-archive reflog-only work" "$lane_nar_reflog"

# A failed push must not delete anything. Release It! 5.5: verify the resource
# you will actually use -- an archive that did not accept the refs is not one.
lane_bad="$HOME/w/lane-badarchive"
clone_lane "$lane_bad"
echo "unmerged" >"$lane_bad/UNMERGED"
git -C "$lane_bad" add UNMERGED
git -C "$lane_bad" commit -q -m "work that never reached main"
run_reap --yes --archive-to "$WORKDIR/does-not-exist.git" "$lane_bad"
assert_contains "unwritable archive" "archive push failed:"
assert_contains "unwritable archive diagnostic" "does not appear to be a git repository"
assert_exists "unwritable archive keeps the lane" "$lane_bad"

# Existing generation refs are intentionally immutable. Diagnose that policy
# wedge distinctly so the operator knows to inspect/preserve the conflicting
# archived tip rather than treating it as a transient transport failure.
lane_conflict="$HOME/w/lane-archive-conflict"
clone_lane "$lane_conflict"
echo conflict >"$lane_conflict/CONFLICT"
git -C "$lane_conflict" add CONFLICT
git -C "$lane_conflict" commit -q -m conflict
conflict_generation="$(generation_of "$lane_conflict")"
conflict_ref="refs/lanes/w/lane-archive-conflict/$conflict_generation/main"
git -C "$lane_conflict" checkout -q -b archived-conflicting-tip HEAD^
echo other >"$lane_conflict/OTHER"
git -C "$lane_conflict" add OTHER
git -C "$lane_conflict" commit -q -m other
conflicting_tip="$(git -C "$lane_conflict" rev-parse HEAD)"
git -C "$lane_conflict" checkout -q main
incoming_tip="$(git -C "$lane_conflict" rev-parse HEAD)"
git -C "$lane_conflict" push -q "$ARCHIVE" "$conflicting_tip:$conflict_ref"
run_reap --yes --archive-to "$ARCHIVE" "$lane_conflict"
assert_rc0 "same-generation supersession archive"
assert_gone "same-generation supersession archive" "$lane_conflict"
archive_has "same-generation primary archive retained" "$conflict_ref" "$conflicting_tip"
archive_has "same-generation incoming superseded" \
  "refs/archive/w/lane-archive-conflict/$conflict_generation/superseded/${incoming_tip:0:12}" \
  "$incoming_tip"

# An uncommitted tree has no commit to archive, so archiving must not weaken it.
lane_ad="$HOME/w/lane-archive-dirty"
clone_lane "$lane_ad"
echo "scratch" >"$lane_ad/NOTES.md"
run_reap --yes --archive-to "$ARCHIVE" "$lane_ad"
assert_contains "archive + dirty" "dirty working tree"
assert_exists "archive + dirty keeps the lane" "$lane_ad"

# Same for a stash: `git push` moves branches, not stash entries.
lane_as="$HOME/w/lane-archive-stash"
clone_lane "$lane_as"
echo "stashed" >"$lane_as/README"
git -C "$lane_as" stash push -q -m "wip"
run_reap --yes --archive-to "$ARCHIVE" "$lane_as"
assert_contains "archive + stash" "stash has real work"
assert_exists "archive + stash keeps the lane" "$lane_as"

# A failed rm is not a reap. Simulate a genuinely partial removal and require a
# durable marker containing the successful archive ref, so a later sweep does
# not misdiagnose the damaged checkout as an ordinary dirty tree.
lane_rm_fail="$HOME/w/lane-rm-fail"
clone_lane "$lane_rm_fail"
rm_fail_bin="$WORKDIR/rm-fail-bin"
mkdir "$rm_fail_bin"
cat >"$rm_fail_bin/rm" <<'FAKE_RM'
#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "$arg" == "${FAIL_RM_PATH:-}" ]]; then
    "$REAL_RM" -rf -- "$arg/.git"
    chmod a-w "$arg"
    exit 1
  fi
done
exec "$REAL_RM" "$@"
FAKE_RM
chmod +x "$rm_fail_bin/rm"
REAL_RM="$(command -v rm)" FAIL_RM_PATH="$lane_rm_fail" \
  PATH="$rm_fail_bin:$PATH" run_reap --yes --archive-to "$ARCHIVE" "$lane_rm_fail"
if [[ "$rc" -eq 1 ]]; then pass "rm failure exits 1"
else fail "rm failure expected exit 1 got $rc; out=$out"; fi
assert_contains "rm failure" "rm failed"
assert_exists "rm failure" "$lane_rm_fail"
assert_contains "rm failure archive context" "rm failed after archive refs/lanes/"
assert_contains "rm failure partial context" "lane partially removed"
partial_intent="$(find "$HOME/.workbay-reap/partial" -type f -name '*.json' -print -quit 2>/dev/null || true)"
if [[ -n "$partial_intent" ]] && grep -q '"archive_ref":"refs/lanes/' "$partial_intent"; then
  pass "rm failure external intent records archive ref"
else
  fail "rm failure external intent missing archive ref"
fi
assert_summary "rm failure" 1 0 1 0
run_reap --yes --archive-to "$ARCHIVE" "$lane_rm_fail"
assert_rc0 "partial rm follow-up"
assert_contains "partial rm follow-up" "partial reap after archive"
assert_contains "partial rm follow-up names intent" "(intent: $HOME/.workbay-reap/partial/"
assert_not_contains "partial rm follow-up" "dirty working tree"
assert_exists "partial rm follow-up" "$lane_rm_fail"
chmod u+w "$lane_rm_fail"

# The sentinel is keyed by path. Once the damaged checkout is replaced by a
# fresh clone at a tip the intent never verified, it is a new lane: retire the
# intent (kept for audit) instead of blocking the occupant forever.
rm -rf "$lane_rm_fail"
clone_lane "$lane_rm_fail"
echo "new occupant" >"$lane_rm_fail/NEW_OCCUPANT"
git -C "$lane_rm_fail" add NEW_OCCUPANT
git -C "$lane_rm_fail" commit -q -m "new occupant work"
run_reap --yes "$lane_rm_fail"
assert_not_contains "new occupant after partial" "partial reap after archive"
assert_contains "new occupant after partial" "stale partial intent superseded by new occupant"
assert_contains "new occupant after partial" "unmerged local work"
assert_exists "new occupant after partial" "$lane_rm_fail"
if [[ -n "$(find "$HOME/.workbay-reap/partial" -type f -name '*.json.stale.*' -print -quit 2>/dev/null || true)" ]] \
  && [[ -z "$(find "$HOME/.workbay-reap/partial" -type f -name '*.json' -print -quit 2>/dev/null || true)" ]]; then
  pass "new occupant retires the intent to a .stale audit file"
else
  fail "new occupant did not retire the intent; dir=$(ls -la "$HOME/.workbay-reap/partial" 2>/dev/null || true)"
fi

# When the HEAD want-entry itself is redirected to the superseded ref, the
# recorded archive ref must point at where this tip actually landed.
lane_head_conflict="$HOME/w/lane-archive-conflict-head"
clone_lane "$lane_head_conflict"
echo head-conflict >"$lane_head_conflict/CONFLICT"
git -C "$lane_head_conflict" add CONFLICT
git -C "$lane_head_conflict" commit -q -m head-conflict
head_generation="$(generation_of "$lane_head_conflict")"
head_conflict_ref="refs/lanes/w/lane-archive-conflict-head/$head_generation/HEAD"
git -C "$lane_head_conflict" checkout -q -b archived-head-tip HEAD^
echo other-head >"$lane_head_conflict/OTHER"
git -C "$lane_head_conflict" add OTHER
git -C "$lane_head_conflict" commit -q -m other-head
head_conflicting_tip="$(git -C "$lane_head_conflict" rev-parse HEAD)"
git -C "$lane_head_conflict" checkout -q main
head_incoming_tip="$(git -C "$lane_head_conflict" rev-parse HEAD)"
git -C "$lane_head_conflict" push -q "$ARCHIVE" "$head_conflicting_tip:$head_conflict_ref"
head_superseded_ref="refs/archive/w/lane-archive-conflict-head/$head_generation/superseded/${head_incoming_tip:0:12}"
REAL_RM="$(command -v rm)" FAIL_RM_PATH="$lane_head_conflict" \
  PATH="$rm_fail_bin:$PATH" run_reap --yes --archive-to "$ARCHIVE" "$lane_head_conflict"
assert_contains "superseded HEAD archive ref" "rm failed after archive $head_superseded_ref"
archive_has "superseded HEAD primary retained" "$head_conflict_ref" "$head_conflicting_tip"
archive_has "superseded HEAD incoming archived" "$head_superseded_ref" "$head_incoming_tip"
head_intent="$(grep -l "lane-archive-conflict-head" "$HOME"/.workbay-reap/partial/*.json 2>/dev/null | head -n1 || true)"
if [[ -n "$head_intent" ]] && grep -q "\"archive_ref\":\"$head_superseded_ref\"" "$head_intent"; then
  pass "superseded HEAD intent records the superseded ref"
else
  fail "superseded HEAD intent missing superseded ref; intent=${head_intent:-none} $(cat "$head_intent" 2>/dev/null || true)"
fi
chmod u+w "$lane_head_conflict"

# Ref enumeration is a destructive-decision input. A failed read must not look
# like an empty ref set and permit deletion of an unarchived alternate branch.
lane_ref_enum_fail="$HOME/ref-enum-root/lane-ref-enumeration-fail"
clone_lane "$lane_ref_enum_fail"
git -C "$lane_ref_enum_fail" checkout -q -b unique-alternate
echo unique >"$lane_ref_enum_fail/UNIQUE"
git -C "$lane_ref_enum_fail" add UNIQUE
git -C "$lane_ref_enum_fail" commit -q -m "unique alternate branch"
unique_alternate_tip="$(git -C "$lane_ref_enum_fail" rev-parse HEAD)"
git -C "$lane_ref_enum_fail" checkout -q main
ref_enum_bin="$WORKDIR/ref-enum-bin"
mkdir "$ref_enum_bin"
cat >"$ref_enum_bin/git" <<'REF_ENUM_GIT'
#!/bin/sh
case " $* " in
  *" for-each-ref "*)
    count=0
    [ ! -f "$REF_ENUM_COUNT" ] || count="$(cat "$REF_ENUM_COUNT")"
    count=$((count + 1))
    printf '%s\n' "$count" >"$REF_ENUM_COUNT"
    if [ "$count" -ge 2 ] && [ "$count" -le 5 ]; then
      echo "simulated ref enumeration failure" >&2
      exit 128
    fi
    ;;
esac
exec "$REAL_GIT" "$@"
REF_ENUM_GIT
chmod +x "$ref_enum_bin/git"
REAL_GIT="$(command -v git)" REF_ENUM_COUNT="$WORKDIR/ref-enum-count" \
  REAP_LANE_ROOTS="ref-enum-root" REAP_DF_ALERT_PCT=0 PATH="$ref_enum_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" --all "$HOME/ref-enum-root"
if [[ "$rc" -ne 0 ]]; then pass "ref enumeration failure pressured exit nonzero"
else fail "ref enumeration failure pressured expected nonzero; out=$out"; fi
assert_contains "ref enumeration failure" "ref enumeration failed"
assert_exists "ref enumeration failure retains lane" "$lane_ref_enum_fail"
assert_summary "ref enumeration failure" 1 0 1 0
if git -C "$ARCHIVE" cat-file -e "$unique_alternate_tip^{commit}" 2>/dev/null; then
  fail "ref enumeration failure unexpectedly archived unique alternate"
else
  pass "ref enumeration failure did not claim alternate was archived"
fi

if command -v timeout >/dev/null 2>&1; then
  lane_net_timeout="$HOME/w/lane-net-timeout"
  clone_lane "$lane_net_timeout"
  net_timeout_bin="$WORKDIR/net-timeout-bin"
  mkdir "$net_timeout_bin"
  cat >"$net_timeout_bin/git" <<'NET_TIMEOUT_GIT'
#!/bin/sh
case " $* " in
  *" ls-remote "*) sleep 30 ;;
esac
exec "$REAL_GIT" "$@"
NET_TIMEOUT_GIT
  chmod +x "$net_timeout_bin/git"
  REAL_GIT="$(command -v git)" REAP_GIT_NET_TIMEOUT_SEC=1 \
    PATH="$net_timeout_bin:$PATH" \
    run_reap --yes --archive-to "$ARCHIVE" "$lane_net_timeout"
  assert_contains "archive network timeout" "archive transport timed out"
  assert_exists "archive network timeout retains lane" "$lane_net_timeout"
  run_reap --yes --archive-to "$ARCHIVE" "$lane_net_timeout"
  assert_rc0 "post-timeout sweep reacquires lock"
else
  echo "SKIP: archive network timeout (timeout unavailable)"
  skips=$((skips + 1))
fi

# Same basename under two roots must not overwrite one another: ~/w/dux-l1 and
# ~/lanes/dux-l1 both exist on the VM, and a basename namespace would archive
# one over the other and then delete both.
sha_w=""
sha_lanes=""
for root in w lanes; do
  lane_c="$HOME/$root/samename"
  clone_lane "$lane_c"
  echo "$root" >"$lane_c/WHICH"
  git -C "$lane_c" add WHICH
  git -C "$lane_c" commit -q -m "$root"
  case "$root" in
    w) sha_w="$(git -C "$lane_c" rev-parse HEAD)"; gen_w="$(generation_of "$lane_c")" ;;
    lanes) sha_lanes="$(git -C "$lane_c" rev-parse HEAD)"; gen_lanes="$(generation_of "$lane_c")" ;;
  esac
  run_reap --yes --archive-to "$ARCHIVE" "$lane_c"
  assert_gone "collision $root" "$lane_c"
done
archive_has "collision" "refs/lanes/w/samename/$gen_w/main" "$sha_w"
archive_has "collision" "refs/lanes/lanes/samename/$gen_lanes/main" "$sha_lanes"

# Re-materializing a path starts a new archive generation. Unrelated histories
# coexist without force-pushing over the only copy of the earlier generation.
lane_re="$HOME/w/lane-rearchive"
mkdir -p "$lane_re"
git init -b main "$lane_re" >/dev/null
git_ident "$lane_re"
echo one >"$lane_re/A"; git -C "$lane_re" add A; git -C "$lane_re" commit -q -m one
re_gen_one="$(generation_of "$lane_re")"
re_sha_one="$(git -C "$lane_re" rev-parse HEAD)"
run_reap --yes --archive-to "$ARCHIVE" "$lane_re"
assert_gone "rearchive first pass" "$lane_re"
mkdir -p "$lane_re"
git init -b main "$lane_re" >/dev/null
git_ident "$lane_re"
echo two >"$lane_re/B"; git -C "$lane_re" add B; git -C "$lane_re" commit -q -m two
re_gen_two="$(generation_of "$lane_re")"
re_sha_two="$(git -C "$lane_re" rev-parse HEAD)"
run_reap --yes --archive-to "$ARCHIVE" "$lane_re"
assert_rc0 "rearchive second generation"
assert_gone "rearchive second generation" "$lane_re"
archive_has "rearchive first generation" \
  "refs/lanes/w/lane-rearchive/$re_gen_one/main" "$re_sha_one"
archive_has "rearchive second generation" \
  "refs/lanes/w/lane-rearchive/$re_gen_two/main" "$re_sha_two"

# A push can report success and still leave the archive empty (a quarantine, a
# hook, a repo that accepts and drops). The lane is deleted on the strength of
# that archive, so the refs must be read back out -- Release It! 5.5: verify the
# resource you will actually use, not the call that was supposed to provide it.
LIAR="$WORKDIR/liar.git"
git init --bare --quiet "$LIAR"
cat >"$LIAR/hooks/post-receive" <<'HOOK'
#!/bin/sh
# Accept the push, then drop what it delivered.
for ref in $(git for-each-ref --format='%(refname)' refs/lanes); do
  git update-ref -d "$ref"
done
HOOK
chmod +x "$LIAR/hooks/post-receive"

lane_liar="$HOME/w/lane-liar"
clone_lane "$lane_liar"
echo liar >"$lane_liar/L"; git -C "$lane_liar" add L; git -C "$lane_liar" commit -q -m liar
run_reap --yes --archive-to "$LIAR" "$lane_liar"
assert_contains "archive that drops refs" "archive verification failed:"
assert_exists "archive that drops refs keeps the lane" "$lane_liar"

# A reset commit is held only by the lane's reflog. Removing the checkout also
# removes that reflog, so preserve each reflog-only commit under an immutable,
# generation-scoped archive ref and prove its tree arrived with it.
lane_reflog="$HOME/w/lane-reflog-only"
clone_lane "$lane_reflog"
echo "reflog only" >"$lane_reflog/REFLOG_ONLY"
git -C "$lane_reflog" add REFLOG_ONLY
git -C "$lane_reflog" commit -q -m "work retained only by reflog"
reflog_sha="$(git -C "$lane_reflog" rev-parse HEAD)"
git -C "$lane_reflog" reset -q --hard HEAD^
reflog_generation="$(generation_of "$lane_reflog")"
run_reap --yes --archive-to "$ARCHIVE" "$lane_reflog"
assert_rc0 "archive reflog-only commit"
assert_gone "archive reflog-only commit" "$lane_reflog"
archive_has "archive reflog-only commit" \
  "refs/reaped/w/lane-reflog-only/$reflog_generation/reflog/$reflog_sha" "$reflog_sha"
if [[ "$(git -C "$ARCHIVE" show "$reflog_sha:REFLOG_ONLY" 2>/dev/null || true)" == "reflog only" ]]; then
  pass "archive reflog-only commit tree is readable"
else
  fail "archive reflog-only commit tree is not readable"
fi

# Archiving can take long enough for another actor to change a non-sandbox
# lane. Synchronize a background writer with the first post-archive `du`, then
# prove the final safety snapshot catches the new commit before rm.
lane_snapshot_race="$HOME/w/lane-snapshot-race"
clone_lane "$lane_snapshot_race"
snapshot_head="$(git -C "$lane_snapshot_race" rev-parse HEAD)"
snapshot_trigger="$WORKDIR/snapshot-trigger"
snapshot_done="$WORKDIR/snapshot-done"
snapshot_writer_exited="$WORKDIR/snapshot-writer-exited"
snapshot_du_bin="$WORKDIR/snapshot-du-bin"
mkdir "$snapshot_du_bin"
cat >"$snapshot_du_bin/du" <<'SNAPSHOT_DU'
#!/usr/bin/env bash
set -e
if [[ ! -e "$SNAPSHOT_TRIGGER" ]]; then
  : >"$SNAPSHOT_TRIGGER"
  attempt=0
  while [[ ! -e "$SNAPSHOT_DONE" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  if [[ ! -e "$SNAPSHOT_DONE" ]]; then
    echo "FAIL: lane snapshot writer did not finish" >&2
    exit 124
  fi
fi
exec "$REAL_DU" "$@"
SNAPSHOT_DU
chmod +x "$snapshot_du_bin/du"
(
  trap ': >"$snapshot_writer_exited"' EXIT
  attempt=0
  while [[ ! -e "$snapshot_trigger" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  [[ -e "$snapshot_trigger" ]] || exit 124
  echo changed >"$lane_snapshot_race/AFTER_SNAPSHOT"
  git -C "$lane_snapshot_race" add AFTER_SNAPSHOT
  git -C "$lane_snapshot_race" commit -q -m "change after safety snapshot"
  : >"$snapshot_done"
) &
snapshot_writer_pid=$!
SNAPSHOT_TRIGGER="$snapshot_trigger" SNAPSHOT_DONE="$snapshot_done" \
  REAL_DU="$(command -v du)" PATH="$snapshot_du_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_snapshot_race"
wait_for_background_pid "$snapshot_writer_pid" "$snapshot_writer_exited" \
  "lane changed after snapshot" || true
assert_rc0 "lane changed after snapshot"
assert_contains "lane changed after snapshot" "lane changed after snapshot; skipped"
assert_exists "lane changed after snapshot" "$lane_snapshot_race"
if [[ "$(git -C "$lane_snapshot_race" rev-parse HEAD)" != "$snapshot_head" ]]; then
  pass "lane changed after snapshot fixture committed"
else
  fail "lane changed after snapshot fixture did not commit; out=$out"
fi

# A commit followed by reset restores HEAD, refs, and status, but changes the
# reflog. Trigger it after reflog archival and prove the final snapshot detects
# that newly orphaned commit rather than deleting its only copy.
lane_reflog_race="$HOME/w/lane-reflog-snapshot-race"
clone_lane "$lane_reflog_race"
reflog_race_head="$(git -C "$lane_reflog_race" rev-parse HEAD)"
reflog_race_trigger="$WORKDIR/reflog-race-trigger"
reflog_race_done="$WORKDIR/reflog-race-done"
reflog_race_writer_exited="$WORKDIR/reflog-race-writer-exited"
reflog_race_du_bin="$WORKDIR/reflog-race-du-bin"
mkdir "$reflog_race_du_bin"
cat >"$reflog_race_du_bin/du" <<'REFLOG_RACE_DU'
#!/usr/bin/env bash
set -e
if [[ ! -e "$REFLOG_RACE_TRIGGER" ]]; then
  : >"$REFLOG_RACE_TRIGGER"
  attempt=0
  while [[ ! -e "$REFLOG_RACE_DONE" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  if [[ ! -e "$REFLOG_RACE_DONE" ]]; then
    echo "FAIL: reflog snapshot writer did not finish" >&2
    exit 124
  fi
fi
exec "$REAL_DU" "$@"
REFLOG_RACE_DU
chmod +x "$reflog_race_du_bin/du"
(
  trap ': >"$reflog_race_writer_exited"' EXIT
  attempt=0
  while [[ ! -e "$reflog_race_trigger" && "$attempt" -lt 1000 ]]; do
    sleep 0.01
    attempt=$((attempt + 1))
  done
  [[ -e "$reflog_race_trigger" ]] || exit 124
  echo reflog-race >"$lane_reflog_race/REFLOG_RACE"
  git -C "$lane_reflog_race" add REFLOG_RACE
  git -C "$lane_reflog_race" commit -q -m "commit then reset after reflog archive"
  git -C "$lane_reflog_race" reset -q --hard "$reflog_race_head"
  : >"$reflog_race_done"
) &
reflog_race_writer_pid=$!
REFLOG_RACE_TRIGGER="$reflog_race_trigger" REFLOG_RACE_DONE="$reflog_race_done" \
  REAL_DU="$(command -v du)" PATH="$reflog_race_du_bin:$PATH" \
  run_reap --yes --archive-to "$ARCHIVE" "$lane_reflog_race"
wait_for_background_pid "$reflog_race_writer_pid" "$reflog_race_writer_exited" \
  "lane reflog changed after snapshot" || true
assert_rc0 "lane reflog changed after snapshot"
assert_contains "lane reflog changed after snapshot" "lane changed after snapshot; skipped"
assert_exists "lane reflog changed after snapshot" "$lane_reflog_race"
if [[ "$(git -C "$lane_reflog_race" rev-parse HEAD)" == "$reflog_race_head" ]] &&
   [[ -n "$(git -C "$lane_reflog_race" reflog --all --format='%H' | grep -v "$reflog_race_head" || true)" ]]; then
  pass "lane reflog changed after snapshot fixture committed and reset"
else
  fail "lane reflog changed after snapshot fixture did not commit and reset; out=$out"
fi

# A detached HEAD is archived too -- commits reachable only from HEAD are the
# easiest work to lose and the hardest to notice missing.
lane_dh="$HOME/w/lane-detached"
clone_lane "$lane_dh"
echo "detached" >"$lane_dh/DETACHED"
git -C "$lane_dh" add DETACHED
git -C "$lane_dh" commit -q -m "detached work"
dh_sha="$(git -C "$lane_dh" rev-parse HEAD)"
dh_generation="$(generation_of "$lane_dh")"
git -C "$lane_dh" checkout -q --detach "$dh_sha"
git -C "$lane_dh" branch -q -D main 2>/dev/null || true
run_reap --yes --archive-to "$ARCHIVE" "$lane_dh"
assert_gone "detached HEAD reaped" "$lane_dh"
archive_has "detached HEAD" "refs/lanes/w/lane-detached/$dh_generation/HEAD" "$dh_sha"

# --- linked worktrees --------------------------------------------------------
# The VM's two biggest roots are not clones at all: all 35 lanes in ~/w and all
# 19 in ~/lanes are linked git worktrees of three parent repos. Their branch
# refs live in the parent, so removing the checkout loses nothing -- and a push
# to a keep-repo cannot even be attempted (the shared object store is served by
# an alternate that no longer holds every parent commit).
#
# Two things still have to be got right, and both destroy work if missed:
#   - a detached HEAD is anchored only by the worktree's own HEAD, which
#     `git worktree prune` deletes; it must become a real ref in the parent.
#   - the parent repo itself sits inside a lane root (~/l1/r7-int is parent to
#     28 lanes). Reaping it takes the object store every one of them shares.

PARENT="$HOME/l1/parentrepo"
clone_lane "$PARENT"

# A main worktree owns the shared object store even in non-archive mode. A
# detached linked worktree has no branch for the ancestry guard to discover.
parent_plain="$HOME/l1/nonarchive-parent"
clone_lane "$parent_plain"
parent_plain_wt="$HOME/w/nonarchive-parent-detached"
git -C "$parent_plain" worktree add -q --detach "$parent_plain_wt" >/dev/null 2>&1
run_reap --yes "$parent_plain"
assert_contains "non-archive parent of detached worktree" "repo has linked worktrees"
assert_exists "non-archive parent of detached worktree" "$parent_plain"
assert_exists "non-archive detached child survives" "$parent_plain_wt"

# Parent metadata must also be pruned when a linked worktree is removed via
# the non-archive ancestry path.
wt_plain="$HOME/w/wt-plain"
git -C "$PARENT" worktree add -q -b lane/wt-plain "$wt_plain" >/dev/null 2>&1
run_reap --yes "$wt_plain"
assert_rc0 "non-archive linked worktree"
assert_gone "non-archive linked worktree" "$wt_plain"
if git -C "$PARENT" worktree list | grep -qF "$wt_plain"; then
  fail "non-archive parent still lists the reaped worktree"
else
  pass "non-archive parent worktree metadata pruned"
fi

wt_branch="$HOME/w/wt-branch"
git -C "$PARENT" worktree add -q -b lane/wt-branch "$wt_branch" >/dev/null 2>&1
echo work >"$wt_branch/W"
git -C "$wt_branch" add W
git -C "$wt_branch" commit -q -m "worktree work"
wt_sha="$(git -C "$wt_branch" rev-parse HEAD)"

run_reap --yes --archive-to "$ARCHIVE" "$wt_branch"
assert_rc0 "worktree on a branch"
assert_gone "worktree on a branch" "$wt_branch"
# The branch is a ref in the parent; it must still be there afterwards.
if [[ "$(git -C "$PARENT" rev-parse --verify --quiet lane/wt-branch)" == "$wt_sha" ]]; then
  pass "worktree branch survives in the parent"
else
  fail "worktree branch lost from the parent"
fi
# Stale worktree metadata left behind makes the parent's `worktree list` lie.
if git -C "$PARENT" worktree list | grep -qF "$wt_branch"; then
  fail "parent still lists the reaped worktree"
else
  pass "parent worktree metadata pruned"
fi

# A detached HEAD has no branch in the parent: prune would orphan the commit.
wt_det="$HOME/w/wt-detached"
git -C "$PARENT" worktree add -q --detach "$wt_det" >/dev/null 2>&1
echo detached >"$wt_det/D"
git -C "$wt_det" add D
git -C "$wt_det" commit -q -m "detached worktree work"
det_sha="$(git -C "$wt_det" rev-parse HEAD)"
det_generation="$(generation_of "$wt_det")"
run_reap --yes --archive-to "$ARCHIVE" "$wt_det"
assert_gone "detached worktree" "$wt_det"
if [[ "$(git -C "$PARENT" rev-parse --verify --quiet \
    "refs/lanes/w/wt-detached/$det_generation/HEAD")" == "$det_sha" ]]; then
  pass "detached worktree HEAD anchored in the parent"
else
  fail "detached worktree HEAD not anchored: commit is now unreachable"
fi

# Uncommitted work in a worktree is still uncommitted work.
wt_dirty="$HOME/w/wt-dirty"
git -C "$PARENT" worktree add -q --detach "$wt_dirty" >/dev/null 2>&1
echo scratch >"$wt_dirty/NOTES.md"
run_reap --yes --archive-to "$ARCHIVE" "$wt_dirty"
assert_contains "dirty worktree" "dirty working tree"
assert_exists "dirty worktree kept" "$wt_dirty"

# The parent must never be reaped: it holds the refs and the object store that
# every worktree above depends on.
run_reap --yes --archive-to "$ARCHIVE" "$PARENT"
assert_contains "parent of live worktrees" "has linked worktrees"
assert_exists "parent of live worktrees kept" "$PARENT"

# ... including when the sweep reaches it via --all.
run_reap --yes --archive-to "$ARCHIVE" --all "$HOME/l1"
assert_exists "parent survives an --all sweep" "$PARENT"

# --all is repeatable: one cron line has to sweep every lane root. With a
# last-one-wins flag the entry would silently reap only the final root.
lane_m1="$HOME/w/lane-multi"
lane_m2="$HOME/lanes/lane-multi"
clone_lane "$lane_m1"
clone_lane "$lane_m2"
run_reap --all "$HOME/w" --all "$HOME/lanes"
assert_rc0 "multi --all"
assert_contains "multi --all first root" "WOULD REAP $lane_m1"
assert_contains "multi --all second root" "WOULD REAP $lane_m2"

# A cron entry names every conventional root, even when a user owns only some
# of them. One absent root must be an explained per-root skip, not an early
# abort that prevents a later existing root from being swept.
lane_mixed_root="$HOME/lanes/lane-mixed-root"
clone_lane "$lane_mixed_root"
run_reap --all "$HOME/root-that-is-absent" --all "$HOME/lanes"
assert_rc0 "mixed present and missing --all roots"
assert_contains "mixed missing --all root warning" \
  "reap-lane: --all root is not a directory: $HOME/root-that-is-absent"
assert_contains "mixed missing --all root skip" \
  "SKIP $HOME/root-that-is-absent: --all root is not a directory"
assert_contains "mixed present --all root swept" "WOULD REAP $lane_mixed_root"

# --all ROOT scans ROOT/* (merged clean sibling is reaped; unmerged sibling kept).
lane_all_ok="$HOME/w3/lane-all-ok"
lane_all_bad="$HOME/w3/lane-all-bad"
clone_lane "$lane_all_ok"
clone_lane "$lane_all_bad"
git -C "$lane_all_bad" checkout -q -b leftover
echo leftover >"$lane_all_bad/leftover.txt"
git -C "$lane_all_bad" add leftover.txt
git -C "$lane_all_bad" commit -q -m "leftover"
run_reap --yes --all "$HOME/w3"
assert_rc0 "--all"
assert_gone "--all merged" "$lane_all_ok"
assert_exists "--all unmerged" "$lane_all_bad"

# A real sweep that sees stale candidates but cannot reclaim any must tell cron
# that the run is stale when disk use is at or above the configurable alert
# level. A direct single-lane guard refusal is a successful no-op, so exercise
# the alert through the same --all mode that cron uses.
alert_root="$HOME/alert-root"
mkdir -p "$alert_root"
lane_alert="$alert_root/lane-alert"
clone_lane "$lane_alert"
echo dirty >>"$lane_alert/README"

# A direct request that reaches a guard is a successful, explained no-op. It
# must not inherit the cron sweep's freshness-alert status, even on a pressured
# filesystem.
REAP_LANE_ROOTS="alert-root" REAP_DF_ALERT_PCT=0 run_reap --yes "$lane_alert"
assert_rc0 "freshness direct guard refusal"
assert_contains "freshness direct guard refusal" "dirty working tree"
assert_exists "freshness direct guard refusal" "$lane_alert"

REAP_LANE_ROOTS="alert-root" REAP_DF_ALERT_PCT=0 run_reap --yes --all "$alert_root"
if [[ "$rc" -eq 4 ]]; then pass "freshness alert exit 4"
else fail "freshness alert expected exit 4 got $rc; out=$out"; fi
assert_summary "freshness alert" 1 0 1 0
assert_exists "freshness alert" "$lane_alert"

# Below the configured pressure threshold, zero reclaimed lanes is a healthy
# no-op and remains exit 0. Use 101 so a host whose volume reports 100% used
# (macOS APFS near-full) cannot trip the alert and fail this healthy case.
REAP_LANE_ROOTS="alert-root" REAP_DF_ALERT_PCT=101 run_reap --yes --all "$alert_root"
assert_rc0 "freshness below threshold"
assert_summary "freshness below threshold" 1 0 1 0

# A completed sweep with no stale candidates is fresh even under an alert
# threshold of zero.
empty_alert_root="$HOME/empty-alert-root"
mkdir -p "$empty_alert_root"
REAP_DF_ALERT_PCT=0 run_reap --yes --all "$empty_alert_root"
assert_rc0 "freshness empty sweep"
assert_summary "freshness empty sweep" 0 0 0 0

# A missing df must fail safe: keep the summary numeric and assume full disk
# pressure instead of silently disabling the exit-4 check.
nodf_bin="$WORKDIR/nodf-bin"
mkdir "$nodf_bin"
# Only df is withheld: the sweep lock's mkdir fallback (hosts without flock,
# e.g. macOS) still needs mkdir/mv/ps/rm/rmdir, and a host without flock must
# not get a dangling symlink.
for command_name in awk bash flock realpath mkdir mv ps rm rmdir; do
  command_path="$(command -v "$command_name" || true)"
  [[ -n "$command_path" ]] || continue
  ln -s "$command_path" "$nodf_bin/$command_name"
done
PATH="$nodf_bin" run_reap --all "$empty_alert_root"
assert_rc0 "df unavailable"
assert_contains "df unavailable" "could not determine filesystem usage"
assert_contains "df unavailable" "df_used_pct=100"

# A dry run never pages cron: it intentionally reaps nothing.
lane_alert_dry="$HOME/w3/lane-alert-dry"
clone_lane "$lane_alert_dry"
REAP_DF_ALERT_PCT=0 run_reap "$lane_alert_dry"
assert_rc0 "freshness dry-run"
assert_contains "freshness dry-run" "WOULD REAP"
assert_summary "freshness dry-run" 1 0 0 0

if [[ "$failures" -gt 0 ]]; then
  echo "${failures} FAILED"
  exit 1
fi
echo "all cases passed, ${skips} skipped"
