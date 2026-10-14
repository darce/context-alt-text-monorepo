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
# GTMC-C81V-RC-M1 / decision 16447: inspect each sweep independently.
home_cron_command="$(sed -n '/^17 .*reap-lane\.sh/p' "$space_crontab" | sed 's/^[^ ]* [^ ]* [^ ]* [^ ]* [^ ]* //')"
remote_cron_command="$(sed -n '/^23 .*reap-lane\.sh/p' "$space_crontab" | sed 's/^[^ ]* [^ ]* [^ ]* [^ ]* [^ ]* //')"
mkdir -p "$space_home/bin"
mv "$space_home/bin/reap-lane.sh" "$space_home/bin/reap-lane.real"
cat >"$space_home/bin/reap-lane.sh" <<'FAKE_REAPER'
#!/bin/sh
printf 'remote=<%s>\n' "${WORKBAY_REMOTE_AGENT_ROOT:-}" >"$CRON_ARGS"
for arg in "$@"; do printf 'arg=<%s>\n' "$arg" >>"$CRON_ARGS"; done
FAKE_REAPER
chmod +x "$space_home/bin/reap-lane.sh"
cron_args="$space_home/cron args.txt"
HOME="$space_home" CRON_ARGS="$cron_args" /bin/sh -c "$home_cron_command"
assert_file_line() {
  if grep -qxF "$2" "$1"; then pass "$3"
  else fail "$3 missing '$2'; file=$(cat "$1" 2>/dev/null || true)"; fi
}
assert_file_line "$cron_args" 'remote=<>' "space HOME home sweep clears remote root"
assert_file_line "$cron_args" "arg=<--archive-to>" "space HOME preserves archive flag"
assert_file_line "$cron_args" "arg=<$space_home/lane-archive.git>" \
  "space HOME preserves archive path"
assert_file_line "$cron_args" "arg=<--all>" "space HOME preserves all flags"
for root in w3 uxw2 l1 w lanes grok-sandbox; do
  assert_file_line "$cron_args" "arg=<$space_home/$root>" \
    "space HOME preserves home root $root"
done
HOME="$space_home" CRON_ARGS="$cron_args" /bin/sh -c "$remote_cron_command"
assert_file_line "$cron_args" "remote=<$space_home/agent sandboxes>" \
  "space HOME preserves remote root"
assert_file_line "$cron_args" "arg=<--archive-to>" "space HOME remote sweep preserves archive flag"
assert_file_line "$cron_args" "arg=<$space_home/lane-archive.git>" \
  "space HOME remote sweep preserves archive path"
assert_file_line "$cron_args" "arg=<$space_home/agent sandboxes>" \
  "space HOME remote sweep preserves all root"
if [[ "$(grep -cxF 'arg=<--all>' "$cron_args")" -eq 1 ]]; then
  pass "space HOME remote sweep has exactly one all root"
else
  fail "space HOME remote sweep must have exactly one all root"
fi

# crontab(5) turns an unescaped % into a newline before the shell ever runs,
# truncating the command. The entry must escape it and survive cron's unescape.
percent_root="$space_home/agent 100% sandboxes"
: >"$space_crontab"
rm -f "$space_home/bin/reap-lane.sh"
HOME="$space_home" CRONTAB_FILE="$space_crontab" \
  WORKBAY_REMOTE_AGENT_ROOT="$percent_root" \
  PATH="$space_home/fakebin:$PATH" bash "$SCRIPT" >/dev/null
percent_line="$(sed -n '/reap-lane\.sh/p' "$space_crontab")"
if [[ "$percent_line" == *'100\%'* ]] && [[ "${percent_line//\\%/}" != *%* ]]; then
  pass "percent in remote root is cron-escaped"
else
  fail "percent in remote root left unescaped; line=$percent_line"
fi
cron_command="$(printf '%s\n' "$percent_line" | sed 's/^[^ ]* [^ ]* [^ ]* [^ ]* [^ ]* //; s/\\%/%/g')"
mv "$space_home/bin/reap-lane.sh" "$space_home/bin/reap-lane.real"
cat >"$space_home/bin/reap-lane.sh" <<'FAKE_REAPER'
#!/bin/sh
printf 'remote=<%s>\n' "${WORKBAY_REMOTE_AGENT_ROOT:-}" >"$CRON_ARGS"
for arg in "$@"; do printf 'arg=<%s>\n' "$arg" >>"$CRON_ARGS"; done
FAKE_REAPER
chmod +x "$space_home/bin/reap-lane.sh"
: >"$cron_args"
HOME="$space_home" CRON_ARGS="$cron_args" /bin/sh -c "$cron_command"
assert_file_line "$cron_args" "remote=<$percent_root>" "percent remote root survives cron unescape"
assert_file_line "$cron_args" "arg=<--archive-to>" "percent remote root keeps archive flag"

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

# New durable-cron cases use an isolated installer/reaper fixture; the existing
# assertions above remain unchanged. [RES-07][RES-25][TEST-15]
durable_passes=0
durable_failures=0
durable_fixture() {
  D_DIR="$WORKDIR/durable-$1"
  mkdir -p "$D_DIR/vm" "$D_DIR/home with spaces"
  cp "${INSTALL_REAP_CRON_TEST_SOURCE:-$SCRIPT}" "$D_DIR/vm/install-reap-cron.sh"
  export HOME="$D_DIR/home with spaces"
  export CRONTAB_FILE="$D_DIR/crontab" D_CALLS="$D_DIR/calls"
  unset WORKBAY_REMOTE_AGENT_ROOT WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC CRONTAB_LIST_ERROR
  : >"$CRONTAB_FILE"
  : >"$D_CALLS"
  cat >"$D_DIR/vm/reap-lane.sh" <<'D_REAPER'
#!/usr/bin/env bash
lane_has_live_process() { return 1; }
{
  printf 'root=<%s>\nttl=<%s>\n' "${WORKBAY_REMOTE_AGENT_ROOT:-}" "${WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC:-}"
  for arg in "$@"; do printf 'arg=<%s>\n' "$arg"; done
} >>"$D_CALLS"
if [[ -n "${D_NESTED_CRON_COMMAND:-}" ]]; then
  # Match the real reaper's reuse of descriptor 9 for its own lock.
  exec 9>"$HOME/reaper-private.lock"
  exec 9>&-
  D_NESTED_CRON_COMMAND='' /bin/sh -c "$D_NESTED_CRON_COMMAND"
fi
echo fixture-reaper-output
exit "${D_REAPER_STATUS:-0}"
D_REAPER
  D_INSTALL="$D_DIR/vm/install-reap-cron.sh"
}
durable_expect() {
  if "$@"; then return 0; fi
  printf '  assertion failed: %s\n' "$*"
  return 1
}
durable_install() {
  D_RC=0
  bash "$D_INSTALL" >"$D_DIR/install-output" 2>&1 || D_RC=$?
}
durable_command() {
  sed -n "/^$1 /s/^[^ ]* [^ ]* [^ ]* [^ ]* [^ ]* //p" "$CRONTAB_FILE" | sed 's/\\%/%/g'
}
durable_run() {
  local command
  command="$(durable_command "$1")"
  [[ -n "$command" ]] || { echo "  missing :$1 cron entry"; return 1; }
  D_RUN_RC=0
  /bin/sh -c "$command" >"$D_DIR/cron-output" 2>&1 || D_RUN_RC=$?
}
durable_case() {
  if (durable_fixture "$1"; "$2"); then
    pass "durable $1"
    durable_passes=$((durable_passes + 1))
  else
    fail "durable $1"
    durable_failures=$((durable_failures + 1))
  fi
}
durable_hourly() {
  durable_install
  durable_expect test "$D_RC" -eq 0 || return 1
  durable_expect grep -q '^17 \* \* \* \* ' "$CRONTAB_FILE" || return 1
  durable_expect test "$(grep -c 'reap-lane\.sh' "$CRONTAB_FILE")" -eq 1 || return 1
  durable_run 17 || return 1
  durable_expect test "$D_RUN_RC" -eq 0 || return 1
  for root in w3 uxw2 l1 w lanes grok-sandbox; do
    durable_expect grep -qxF "arg=<$HOME/$root>" "$D_CALLS" || return 1
  done
  durable_expect grep -qxF 'root=<>' "$D_CALLS"
}
durable_remote() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents 100% \"quoted\" \$literal \`literal\` \\tail"
  durable_install
  durable_expect test "$D_RC" -eq 0 || return 1
  durable_expect grep -q '^23 \* \* \* \* ' "$CRONTAB_FILE" || return 1
  durable_expect test "$(grep -c 'reap-lane\.sh' "$CRONTAB_FILE")" -eq 2 || return 1
  local home_entry remote_entry
  home_entry="$(sed -n '/^17 /p' "$CRONTAB_FILE")"
  remote_entry="$(sed -n '/^23 /p' "$CRONTAB_FILE")"
  durable_expect test "${home_entry#*WORKBAY_REMOTE_AGENT_ROOT}" = "$home_entry" || return 1
  [[ "$remote_entry" == *'100\%'* ]] || return 1
  [[ "${remote_entry//\\%/}" != *%* ]] || return 1
  durable_run 17 || return 1
  durable_expect grep -qxF 'root=<>' "$D_CALLS" || return 1
  : >"$D_CALLS"
  durable_run 23 || return 1
  durable_expect test "$D_RUN_RC" -eq 0 || return 1
  durable_expect grep -qxF "root=<$WORKBAY_REMOTE_AGENT_ROOT>" "$D_CALLS" || return 1
  durable_expect grep -qxF 'ttl=<3600>' "$D_CALLS" || return 1
  durable_expect grep -qxF "arg=<$WORKBAY_REMOTE_AGENT_ROOT>" "$D_CALLS" || return 1
  durable_expect test "$(grep -c '^arg=<--all>$' "$D_CALLS")" -eq 1 || return 1
  durable_expect grep -qxF "arg=<$HOME/lane-archive.git>" "$D_CALLS"
}
durable_override() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents" WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC=900
  durable_install
  durable_expect test "$D_RC" -eq 0 || return 1
  durable_run 23 || return 1
  durable_expect grep -qxF 'ttl=<900>' "$D_CALLS" || return 1
  export WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC=21600
  durable_install
  : >"$D_CALLS"
  durable_run 23 || return 1
  durable_expect grep -qxF 'ttl=<21600>' "$D_CALLS" || return 1
  export WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC=00900
  durable_install
  : >"$D_CALLS"
  durable_run 23 || return 1
  durable_expect grep -qxF 'ttl=<900>' "$D_CALLS"
}
durable_invalid_ttl() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents"
  mkdir -p "$HOME/bin"
  printf 'installed sentinel\n' >"$HOME/bin/reap-lane.sh"
  cp "$HOME/bin/reap-lane.sh" "$D_DIR/copy-before"
  printf '# user comment\n0 3 * * * user-job\n' >"$CRONTAB_FILE"
  cp "$CRONTAB_FILE" "$D_DIR/cron-before"
  local ttl
  for ttl in 899 0 -1 1.5 oops '900;echo bad' ''; do
    export WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC="$ttl"
    durable_install
    durable_expect test "$D_RC" -ne 0 || return 1
    durable_expect cmp -s "$CRONTAB_FILE" "$D_DIR/cron-before" || return 1
    durable_expect cmp -s "$HOME/bin/reap-lane.sh" "$D_DIR/copy-before" || return 1
  done
}
durable_converge() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents"
  cat >"$D_DIR/unrelated" <<'D_UNRELATED'
# unrelated comment mentions reap-lane.sh

  # user spacing and trailing spaces preserved  
0 3 * * * /usr/bin/some-other-job
5 3 * * * /usr/bin/user-job # reminder about reap-lane.sh
7 3 * * * /usr/bin/reap-lane.sh.backup


D_UNRELATED
  cat "$D_DIR/unrelated" >"$CRONTAB_FILE"
  cat >>"$CRONTAB_FILE" <<'D_OLD_CRON'
17 * * * * "$HOME/bin/reap-lane.sh" --yes --archive-to "$HOME/lane-archive.git" --all "$HOME/w3" --all "$HOME/uxw2" --all "$HOME/l1" --all "$HOME/w" --all "$HOME/lanes" --all "$HOME/grok-sandbox" >> "$HOME/reap-lane.log" 2>&1
23 * * * * WORKBAY_REMOTE_AGENT_ROOT=/home/gate/workbay-sandbox WORKBAY_REMOTE_AGENT_SANDBOX_TTL_SEC=21600 "$HOME/bin/reap-lane.sh" --yes --archive-to "$HOME/lane-archive.git" --all /home/gate/workbay-sandbox >> "$HOME/reap-lane.log" 2>&1
# acx-reap-lane
17 6 * * 1 /fixture/reap-lane.sh --all /fixture/old
D_OLD_CRON
  durable_install
  durable_expect test "$D_RC" -eq 0 || return 1
  sed '/^# acx-reap-lane$/,$d' "$CRONTAB_FILE" >"$D_DIR/unrelated-after"
  durable_expect cmp -s "$D_DIR/unrelated" "$D_DIR/unrelated-after" || return 1
  durable_expect test "$(grep -c '^[12][37] .*reap-lane\.sh' "$CRONTAB_FILE")" -eq 2 || return 1
  cp "$CRONTAB_FILE" "$D_DIR/first-install"
  durable_install
  durable_expect cmp -s "$CRONTAB_FILE" "$D_DIR/first-install" || return 1
  unset WORKBAY_REMOTE_AGENT_ROOT
  durable_install
  durable_expect test "$(grep -c '^[12][37] .*reap-lane\.sh' "$CRONTAB_FILE")" -eq 1
}
durable_old_source() {
  mkdir -p "$HOME/bin"
  printf 'installed sentinel\n' >"$HOME/bin/reap-lane.sh"
  cp "$HOME/bin/reap-lane.sh" "$D_DIR/copy-before"
  printf '# user comment\n0 3 * * * user-job\n' >"$CRONTAB_FILE"
  cp "$CRONTAB_FILE" "$D_DIR/cron-before"
  printf '#!/bin/sh\n# lane_has_live_process is absent\nexit 0\n' >"$D_DIR/vm/reap-lane.sh"
  durable_install
  durable_expect test "$D_RC" -ne 0 || return 1
  durable_expect cmp -s "$CRONTAB_FILE" "$D_DIR/cron-before" || return 1
  durable_expect cmp -s "$HOME/bin/reap-lane.sh" "$D_DIR/copy-before"
}
durable_lock() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents"
  durable_install
  durable_expect test "$D_RC" -eq 0 || return 1
  exec 8>"$HOME/.reap-lane.cron.lock"
  flock -n 8 || return 1
  local minute
  for minute in 17 23; do
    durable_run "$minute" || return 1
    durable_expect test "$D_RUN_RC" -eq 0 || return 1
  done
  durable_expect test ! -s "$D_CALLS" || return 1
  durable_expect test "$(grep -cxF 'reap-lane: skipped, previous sweep still running' "$HOME/reap-lane.log")" -eq 2 || return 1
  durable_expect test "$(wc -l <"$HOME/reap-lane.log")" -eq 2 || return 1
  exec 8>&-
  durable_run 17 || return 1
  durable_expect test -s "$D_CALLS"
}
durable_exit_status() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents" D_REAPER_STATUS=4
  durable_install
  local minute status
  for status in 4 7 0; do
    export D_REAPER_STATUS="$status"
    for minute in 17 23; do
      durable_run "$minute" || return 1
      durable_expect test "$D_RUN_RC" -eq "$status" || return 1
    done
  done
}
durable_lock_lifetime() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents"
  durable_install
  export D_NESTED_CRON_COMMAND="$(durable_command 23)"
  durable_run 17 || return 1
  durable_expect test "$D_RUN_RC" -eq 0 || return 1
  durable_expect test "$(grep -c '^root=' "$D_CALLS")" -eq 1 || return 1
  durable_expect grep -qxF 'reap-lane: skipped, previous sweep still running' "$HOME/reap-lane.log" || return 1
  unset D_NESTED_CRON_COMMAND
  durable_run 23 || return 1
  durable_expect test "$(grep -c '^root=' "$D_CALLS")" -eq 2
}
durable_rotate() {
  export WORKBAY_REMOTE_AGENT_ROOT="$HOME/agents"
  durable_install
  truncate -s 33554432 "$HOME/reap-lane.log"
  durable_run 17 || return 1
  durable_expect test ! -e "$HOME/reap-lane.log.1" || return 1
  truncate -s 33554433 "$HOME/reap-lane.log"
  printf old-generation >"$HOME/reap-lane.log.1"
  durable_run 23 || return 1
  durable_expect test "$(stat -c %s "$HOME/reap-lane.log.1")" -eq 33554433 || return 1
  durable_expect grep -qxF fixture-reaper-output "$HOME/reap-lane.log" || return 1
  truncate -s 33554434 "$HOME/reap-lane.log"
  durable_run 17 || return 1
  durable_expect test "$(stat -c %s "$HOME/reap-lane.log.1")" -eq 33554434 || return 1
  durable_expect test ! -e "$HOME/reap-lane.log.2"
}
durable_case hourly durable_hourly
durable_case remote-default-quoting durable_remote
durable_case ttl-override durable_override
durable_case ttl-validation durable_invalid_ttl
durable_case converge-byte-preservation durable_converge
durable_case missing-live-probe durable_old_source
durable_case shared-nonblocking-lock durable_lock
durable_case reaper-exit-status durable_exit_status
durable_case lock-survives-reaper-fd-reuse durable_lock_lifetime
durable_case bounded-log-rotation durable_rotate
printf 'DURABLE_COUNTS pass=%s fail=%s\n' "$durable_passes" "$durable_failures"

echo
if [[ "$failures" -gt 0 ]]; then
  echo "$failures FAILED"
  exit 1
fi
echo "all cases passed"
