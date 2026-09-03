#!/usr/bin/env bash
# Pure-local tests for install-reap-cron.sh. No real crontab is touched: a fake
# `crontab` on PATH backs onto a file.
#
# The installer is the reclaimer's own delivery path, so it has to roll forward.
# VMDISK-1: the VM was already carrying an entry that swept only ~/w3, and the
# marker check made re-running the installer a no-op -- widening the roots in
# reap-lane.sh would have shipped a fix that never reached the machine.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SCRIPT="${ROOT}/scripts/vm/install-reap-cron.sh"

failures=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; failures=$((failures + 1)); }

[[ -f "$SCRIPT" ]] || { echo "FAIL: missing $SCRIPT"; exit 1; }

WORKDIR="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/reap-cron-test.XXXXXX")" && pwd -P)"
trap 'rm -rf "$WORKDIR"' EXIT
export HOME="$WORKDIR"

# HOME is redirected above, so ~/.gitconfig is out of scope and `git commit-tree`
# (the canary below) falls back to auto-detecting user@hostname. On a host whose
# hostname has no domain that yields `gate@host.(none)` and git aborts. Pin the
# identity so the canary is hermetic rather than host-dependent.
export GIT_AUTHOR_NAME="reap-cron-test" GIT_AUTHOR_EMAIL="reap-cron-test@invalid"
export GIT_COMMITTER_NAME="reap-cron-test" GIT_COMMITTER_EMAIL="reap-cron-test@invalid"

# Fake crontab: `-l` prints the file, `-` replaces it from stdin.
mkdir -p "$WORKDIR/fakebin"
export CRONTAB_FILE="$WORKDIR/crontab.txt"
cat >"$WORKDIR/fakebin/crontab" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  -l)
    if [[ -n "${CRONTAB_LIST_ERROR:-}" ]]; then
      printf '%s\n' "$CRONTAB_LIST_ERROR" >&2
      exit 1
    fi
    if [[ ! -s "$CRONTAB_FILE" ]]; then
      echo "no crontab for reap-test" >&2
      exit 1
    fi
    cat "$CRONTAB_FILE"
    ;;
  -)  cat >"$CRONTAB_FILE" ;;
  *)  echo "fake crontab: unsupported: $*" >&2; exit 2 ;;
esac
FAKE
chmod +x "$WORKDIR/fakebin/crontab"
export PATH="$WORKDIR/fakebin:$PATH"

run_install() {
  out=""
  rc=0
  out="$(bash "$SCRIPT" 2>&1)" || rc=$?
}

assert_rc0() {
  if [[ "$rc" -eq 0 ]]; then pass "$1 exit 0"; else fail "$1 exit $rc; out=$out"; fi
}

assert_one_marker() {
  local n
  n="$(count_marker)"
  if [[ "$n" -eq 1 ]]; then pass "$1 keeps exactly one marker"; else fail "$1 left $n markers"; fi
}
assert_cron_contains() {
  # -e: the needles include leading `--`, which grep would read as an option.
  if grep -qFe "$2" "$CRONTAB_FILE"; then pass "$1 crontab contains $2"
  else fail "$1 crontab missing '$2'; crontab=$(cat "$CRONTAB_FILE")"; fi
}
assert_cron_absent() {
  if grep -qFe "$2" "$CRONTAB_FILE"; then fail "$1 crontab still has '$2'"
  else pass "$1 crontab free of $2"; fi
}
count_marker() { grep -cF '# acx-reap-lane' "$CRONTAB_FILE" || true; }
file_inode() {
  stat -c %i "$1" 2>/dev/null || stat -f %i "$1"
}

# --- fresh install ------------------------------------------------------------
: >"$CRONTAB_FILE"
run_install
assert_rc0 "fresh"

if [[ -x "$HOME/bin/reap-lane.sh" ]]; then pass "fresh installs the script"
else fail "fresh: $HOME/bin/reap-lane.sh not executable"; fi

# Every root that accumulates lanes must be swept, not just w3.
# Asserted as a whole `--all $HOME/<root> ` token: a bare "$HOME/w" substring
# would be satisfied by "$HOME/w3" and the widening would go unnoticed.
for root in w3 uxw2 l1 w lanes grok-sandbox; do
  assert_cron_contains "fresh" "--all \"\$HOME/$root\""
done

# The weekly sweep must archive, not just guard. Ancestry alone skips every lane
# of a squash-merged wave, which is how the VM reached 94% with the cron
# reporting success every week.
# shellcheck disable=SC2016  # literal $HOME: cron expands it, not us.
assert_cron_contains "fresh" '--archive-to "$HOME/lane-archive.git"'

if git -C "$HOME/lane-archive.git" rev-parse --is-bare-repository >/dev/null 2>&1; then
  pass "fresh creates the keep-repo"
else
  fail "fresh: $HOME/lane-archive.git is not a bare repo"
fi

# The keep-repo may be the only copy of a reaped lane's history: re-running the
# installer must never re-init over it.
git -C "$HOME/lane-archive.git" update-ref refs/lanes/canary/main \
  "$(git -C "$HOME/lane-archive.git" commit-tree -m canary \
      "$(git -C "$HOME/lane-archive.git" hash-object -w -t tree /dev/null)")"
canary="$(git -C "$HOME/lane-archive.git" rev-parse refs/lanes/canary/main)"
run_install
if [[ "$(git -C "$HOME/lane-archive.git" rev-parse refs/lanes/canary/main 2>/dev/null)" == "$canary" ]]; then
  pass "reinstall preserves archived refs"
else
  fail "reinstall destroyed the keep-repo contents"
fi

# --- idempotence: a second run must not duplicate the entry -------------------
run_install
assert_rc0 "rerun"
assert_one_marker "rerun"

# --- roll-forward: a stale narrow entry is REPLACED, not preserved ------------
cat >"$CRONTAB_FILE" <<'STALE'
0 3 * * * /usr/bin/some-other-job
# acx-reap-lane
17 6 * * 1 $HOME/bin/reap-lane.sh --yes --all $HOME/w3 >> $HOME/reap-lane.log 2>&1
STALE
run_install
assert_rc0 "roll-forward"
assert_cron_contains "roll-forward" "--all \"\$HOME/lanes\""
# shellcheck disable=SC2016  # literal $HOME: this is cron text, not a path here.
assert_cron_absent "roll-forward" '--all $HOME/w3 >>'
assert_one_marker "roll-forward"

# An unrelated entry belonging to someone else must survive untouched.
assert_cron_contains "roll-forward" "/usr/bin/some-other-job"

# Blank/comment lines inside an older managed block must not end the removal
# state before its stale command is reached.
cat >"$CRONTAB_FILE" <<'STALE_WITH_BLANK'
0 3 * * * /usr/bin/some-other-job
# acx-reap-lane

# legacy managed command follows
17 6 * * 1 $HOME/bin/reap-lane.sh --yes --all $HOME/w3 >> $HOME/reap-lane.log 2>&1
STALE_WITH_BLANK
run_install
assert_rc0 "roll-forward with blank"
assert_one_marker "roll-forward with blank"
if [[ "$(grep -cF 'reap-lane.sh' "$CRONTAB_FILE" || true)" -eq 1 ]]; then
  pass "roll-forward with blank keeps exactly one managed entry"
else
  fail "roll-forward with blank duplicated managed entry; crontab=$(cat "$CRONTAB_FILE")"
fi
assert_cron_contains "roll-forward with blank" "/usr/bin/some-other-job"

# Cron invokes /bin/sh, so every HOME-derived token must survive spaces and a
# configured remote-agent root must be exported to the installed reaper.
space_home="$WORKDIR/home with space"
mkdir -p "$space_home/fakebin"
cp "$WORKDIR/fakebin/crontab" "$space_home/fakebin/crontab"
space_crontab="$space_home/crontab.txt"
: >"$space_crontab"
HOME="$space_home" CRONTAB_FILE="$space_crontab" \
  WORKBAY_REMOTE_AGENT_ROOT="$space_home/agent sandboxes" \
  PATH="$space_home/fakebin:$PATH" bash "$SCRIPT" >/dev/null
cron_command="$(sed -n '/reap-lane\.sh/p' "$space_crontab" | sed 's/^[^ ]* [^ ]* [^ ]* [^ ]* [^ ]* //')"
mkdir -p "$space_home/bin"
mv "$space_home/bin/reap-lane.sh" "$space_home/bin/reap-lane.real"
cat >"$space_home/bin/reap-lane.sh" <<'FAKE_REAPER'
#!/bin/sh
printf 'remote=<%s>\n' "${WORKBAY_REMOTE_AGENT_ROOT:-}" >"$CRON_ARGS"
for arg in "$@"; do printf 'arg=<%s>\n' "$arg" >>"$CRON_ARGS"; done
FAKE_REAPER
chmod +x "$space_home/bin/reap-lane.sh"
cron_args="$space_home/cron args.txt"
HOME="$space_home" CRON_ARGS="$cron_args" /bin/sh -c "$cron_command"
assert_file_line() {
  if grep -qxF "$2" "$1"; then pass "$3"
  else fail "$3 missing '$2'; file=$(cat "$1" 2>/dev/null || true)"; fi
}
assert_file_line "$cron_args" "remote=<$space_home/agent sandboxes>" \
  "space HOME preserves remote root"
assert_file_line "$cron_args" "arg=<--archive-to>" "space HOME preserves archive flag"
assert_file_line "$cron_args" "arg=<$space_home/lane-archive.git>" \
  "space HOME preserves archive path"
assert_file_line "$cron_args" "arg=<--all>" "space HOME preserves all flags"
assert_file_line "$cron_args" "arg=<$space_home/grok-sandbox>" \
  "space HOME preserves root path"

# A listing error other than the platform's no-crontab diagnostic must abort
# without piping an empty replacement over the user's existing jobs.
crontab_before_error="$(cat "$CRONTAB_FILE")"
CRONTAB_LIST_ERROR="crontab: permission denied" run_install
if [[ "$rc" -ne 0 ]]; then
  pass "crontab read failure exits nonzero"
else
  fail "crontab read failure unexpectedly exited zero; out=$out"
fi
if [[ "$out" == *"crontab: permission denied"* ]]; then
  pass "crontab read failure reports diagnostic"
else
  fail "crontab read failure hid diagnostic; out=$out"
fi
if [[ "$(cat "$CRONTAB_FILE")" == "$crontab_before_error" ]]; then
  pass "crontab read failure preserves existing jobs"
else
  fail "crontab read failure replaced existing jobs"
fi

# --- the installed copy is the current one, not a stale one -------------------
printf '# stale\n' >"$HOME/bin/reap-lane.sh"
installed_inode_before="$(file_inode "$HOME/bin/reap-lane.sh")"
run_install
if cmp -s "$HOME/bin/reap-lane.sh" "${ROOT}/scripts/vm/reap-lane.sh"; then
  pass "reinstall refreshes the copied script"
else
  fail "reinstall left a stale $HOME/bin/reap-lane.sh"
fi
installed_inode_after="$(file_inode "$HOME/bin/reap-lane.sh")"
if [[ "$installed_inode_after" != "$installed_inode_before" ]]; then
  pass "reinstall atomically replaces the installed inode"
else
  fail "reinstall overwrote the installed script in place"
fi

echo
if [[ "$failures" -gt 0 ]]; then
  echo "$failures FAILED"
  exit 1
fi
echo "all cases passed"
