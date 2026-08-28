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

init_origin

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

# Unmerged work is reaped once it is archived -- and every branch lands.
lane_ar="$HOME/w/lane-archive"
clone_lane "$lane_ar"
echo "unmerged" >"$lane_ar/UNMERGED"
git -C "$lane_ar" add UNMERGED
git -C "$lane_ar" commit -q -m "work that never reached main"
git -C "$lane_ar" branch second-branch
ar_sha="$(git -C "$lane_ar" rev-parse HEAD)"
run_reap --yes --archive-to "$ARCHIVE" "$lane_ar"
assert_rc0 "archive reap"
assert_gone "archive reap" "$lane_ar"
archive_has "archive reap" "refs/lanes/w/lane-archive/main" "$ar_sha"
archive_has "archive reap" "refs/lanes/w/lane-archive/second-branch" "$ar_sha"

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
    w) sha_w="$(git -C "$lane_c" rev-parse HEAD)" ;;
    lanes) sha_lanes="$(git -C "$lane_c" rev-parse HEAD)" ;;
  esac
  run_reap --yes --archive-to "$ARCHIVE" "$lane_c"
  assert_gone "collision $root" "$lane_c"
done
archive_has "collision" "refs/lanes/w/samename/main" "$sha_w"
archive_has "collision" "refs/lanes/lanes/samename/main" "$sha_lanes"

# Re-archiving a path whose history diverged must refuse rather than force: the
# refs already there are the only copy of that lane's work.
lane_re="$HOME/w/lane-rearchive"
clone_lane "$lane_re"
echo one >"$lane_re/A"; git -C "$lane_re" add A; git -C "$lane_re" commit -q -m one
run_reap --yes --archive-to "$ARCHIVE" "$lane_re"
assert_gone "rearchive first pass" "$lane_re"
clone_lane "$lane_re"
echo two >"$lane_re/B"; git -C "$lane_re" add B; git -C "$lane_re" commit -q -m two
run_reap --yes --archive-to "$ARCHIVE" "$lane_re"
assert_contains "rearchive diverged" "could not archive"
assert_exists "rearchive diverged keeps the lane" "$lane_re"

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
git -C "$lane_dh" checkout -q --detach "$dh_sha"
git -C "$lane_dh" branch -q -D main 2>/dev/null || true
run_reap --yes --archive-to "$ARCHIVE" "$lane_dh"
assert_gone "detached HEAD reaped" "$lane_dh"
archive_has "detached HEAD" "refs/lanes/w/lane-detached/HEAD" "$dh_sha"

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

if [[ "$failures" -gt 0 ]]; then
  echo "${failures} FAILED"
  exit 1
fi
echo "all cases passed"
