#!/usr/bin/env bash
# Pure-local tests for reap-lane.sh (no network). Exit non-zero on any failure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT}/scripts/vm/reap-lane.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

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

assert_exists() {
  local label="$1" path="$2"
  if [[ -d "$path" ]]; then
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
for command_name in bash mkdir mv ps rm rmdir; do
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
if command -v flock >/dev/null 2>&1; then
  run_reap "$lane_gs"
  assert_rc0 "g2 grok-sandbox"
  assert_contains "g2 grok-sandbox" "WOULD REAP"
fi

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

# The generic lane sweep must honor the remote sandbox lifecycle before it
# archives or deletes anything: marker TTL, occupancy lease, and per-lane lock.
lane_gs_fresh="$HOME/grok-sandbox/feature-fresh-abc12345"
clone_lane "$lane_gs_fresh"
mark_sandbox "$lane_gs_fresh"
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

  # Pre-marker legacy sandboxes enter the canonical marker-gated path only
  # after their directory itself has aged past the sandbox TTL.
  lane_gs_legacy_dirty="$HOME/grok-sandbox/feature-legacy-dirty-abc12345"
  clone_lane "$lane_gs_legacy_dirty"
  echo dirty >>"$lane_gs_legacy_dirty/README"
  touch -t 200001010000 "$lane_gs_legacy_dirty"
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_legacy_dirty"
  assert_contains "grok-sandbox dirty legacy" "dirty working tree"
  assert_exists "grok-sandbox dirty legacy" "$lane_gs_legacy_dirty"
  if [[ ! -e "$lane_gs_legacy_dirty/.workbay-lane-sandbox" ]]; then
    pass "grok-sandbox dirty legacy did not persist marker backfill"
  else
    fail "grok-sandbox dirty legacy persisted marker backfill"
  fi

  lane_gs_legacy="$HOME/grok-sandbox/feature-legacy-abc12345"
  clone_lane "$lane_gs_legacy"
  legacy_key="${lane_gs_legacy##*/}"
  : >"$HOME/grok-sandbox/.lane-lock-$legacy_key"
  printf 'issued=1\nexpiry=2\n' >"$HOME/grok-sandbox/.lane-live-$legacy_key"
  mkdir "$HOME/grok-sandbox/.venv-lane-$legacy_key"
  : >"$HOME/grok-sandbox/.venv-sync-stamp-$legacy_key"
  touch -t 200001010000 "$lane_gs_legacy"
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_legacy"
  assert_rc0 "grok-sandbox stale legacy marker backfill"
  assert_gone "grok-sandbox stale legacy marker backfill" "$lane_gs_legacy"
  assert_gone "grok-sandbox stale legacy lane lock" "$HOME/grok-sandbox/.lane-lock-$legacy_key"
  assert_gone "grok-sandbox stale legacy lease" "$HOME/grok-sandbox/.lane-live-$legacy_key"
  assert_gone "grok-sandbox stale legacy venv" "$HOME/grok-sandbox/.venv-lane-$legacy_key"
  assert_gone "grok-sandbox stale legacy sync stamp" "$HOME/grok-sandbox/.venv-sync-stamp-$legacy_key"
fi

lane_gs_leased="$HOME/grok-sandbox/feature-leased-abc12345"
clone_lane "$lane_gs_leased"
mark_sandbox "$lane_gs_leased"
touch -t 200001010000 "$lane_gs_leased/.workbay-lane-sandbox"
now_epoch="$(date +%s)"
printf 'pid=%s\nissued=%s\nexpiry=%s\n' "$$" "$now_epoch" "$((now_epoch + 3600))" \
  >"$HOME/grok-sandbox/.lane-live-${lane_gs_leased##*/}"
run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_leased"
assert_rc0 "grok-sandbox live lease"
assert_contains "grok-sandbox live lease" "sandbox lease is live"
assert_exists "grok-sandbox live lease" "$lane_gs_leased"
archive_lacks_namespace "grok-sandbox live lease" "grok-sandbox/${lane_gs_leased##*/}"

if command -v flock >/dev/null 2>&1; then
  lane_gs_locked="$HOME/grok-sandbox/feature-locked-abc12345"
  clone_lane "$lane_gs_locked"
  mark_sandbox "$lane_gs_locked"
  touch -t 200001010000 "$lane_gs_locked/.workbay-lane-sandbox"
  lane_gs_lock="$HOME/grok-sandbox/.lane-lock-${lane_gs_locked##*/}"
  rm -f "$lock_ready" "$lock_release"
  (
    exec 7>>"$lane_gs_lock"
    flock 7
    : >"$lock_ready"
    while [[ ! -e "$lock_release" ]]; do sleep 0.05; done
  ) &
  lock_holder_pid=$!
  for _ in {1..100}; do [[ -e "$lock_ready" ]] && break; sleep 0.05; done
  run_reap --yes --archive-to "$ARCHIVE" "$lane_gs_locked"
  assert_rc0 "grok-sandbox lane lock"
  assert_contains "grok-sandbox lane lock" "sandbox lane lock is held"
  assert_exists "grok-sandbox lane lock" "$lane_gs_locked"
  archive_lacks_namespace "grok-sandbox lane lock" "grok-sandbox/${lane_gs_locked##*/}"
  : >"$lock_release"
  wait "$lock_holder_pid"
fi

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

# A failed push must not delete anything. Release It! 5.5: verify the resource
# you will actually use -- an archive that did not accept the refs is not one.
lane_bad="$HOME/w/lane-badarchive"
clone_lane "$lane_bad"
echo "unmerged" >"$lane_bad/UNMERGED"
git -C "$lane_bad" add UNMERGED
git -C "$lane_bad" commit -q -m "work that never reached main"
run_reap --yes --archive-to "$WORKDIR/does-not-exist.git" "$lane_bad"
assert_contains "unwritable archive" "could not archive"
assert_exists "unwritable archive keeps the lane" "$lane_bad"

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

# A failed rm is not a reap: keep the lane, omit the success log/counters, and
# return an internal-error status so automation cannot report false progress.
lane_rm_fail="$HOME/w/lane-rm-fail"
clone_lane "$lane_rm_fail"
rm_fail_bin="$WORKDIR/rm-fail-bin"
mkdir "$rm_fail_bin"
cat >"$rm_fail_bin/rm" <<'FAKE_RM'
#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "$arg" == "${FAIL_RM_PATH:-}" ]]; then
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
assert_summary "rm failure" 1 0 1 0
run_reap --yes --archive-to "$ARCHIVE" "$lane_rm_fail"
assert_gone "rm retry" "$lane_rm_fail"

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
assert_contains "archive that drops refs" "could not archive"
assert_exists "archive that drops refs keeps the lane" "$lane_liar"

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
# no-op and remains exit 0.
REAP_LANE_ROOTS="alert-root" REAP_DF_ALERT_PCT=100 run_reap --yes --all "$alert_root"
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
echo "all cases passed"
